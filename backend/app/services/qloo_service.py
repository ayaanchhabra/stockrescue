"""Thin, defensive client for the Qloo API.

Verified from public hackathon projects (NOT yet from our own key): base URL
https://hackathon.api.qloo.com, header X-Api-Key, GET /search, GET /v2/insights
(filter.type, signal.interests.entities, filter.exclude.entities, take).
Run qloo_smoke_test.py with our real key to confirm response field names.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import httpx

from app.config import settings
from app.schemas.qloo import (InsightEntity, InsightsResult, MatchStatus,
                              QlooCandidate, ResolveResult)

log = logging.getLogger(__name__)
BOOK = "urn:entity:book"
MAX_ATTEMPTS = 3


class QlooError(Exception):
    """kind: not_configured | auth | timeout | rate_limited | upstream | bad_response"""

    def __init__(self, message: str, kind: str = "upstream", status_code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


# ---------------- low-level HTTP: timeout, retry, cache ----------------
_cache: dict[str, tuple[float, Any]] = {}


def clear_cache() -> None:
    _cache.clear()


def _request(path: str, params: dict) -> tuple[Any, bool]:
    """Returns (json, from_cache). Never logs the API key."""
    if not settings.qloo_api_key:
        raise QlooError("QLOO_API_KEY is not set", kind="not_configured")

    key = path + "?" + json.dumps(params, sort_keys=True, default=str)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < settings.qloo_cache_ttl_seconds:
        return hit[1], True

    last: QlooError | None = None
    for attempt in range(MAX_ATTEMPTS):
        wait = float(min(2 ** attempt, 5))
        try:
            r = httpx.get(
                settings.qloo_base_url + path,
                params=params,
                headers={"X-Api-Key": settings.qloo_api_key},
                timeout=settings.qloo_timeout_seconds,
            )
        except httpx.TimeoutException:
            last = QlooError("Qloo request timed out", kind="timeout")
        except httpx.HTTPError as e:
            last = QlooError(f"Network error talking to Qloo ({type(e).__name__})", kind="upstream")
        else:
            code = r.status_code
            if code == 200:
                try:
                    data = r.json()
                except ValueError:
                    raise QlooError("Qloo returned non-JSON", kind="bad_response", status_code=code)
                _cache[key] = (time.time(), data)
                return data, False
            if code in (401, 403):
                raise QlooError("Qloo rejected the API key", kind="auth", status_code=code)
            if code == 404 and path == "/search":
                return {"results": []}, False  # "no results" == no match
            if code == 429 or code >= 500:
                last = QlooError(f"Qloo returned {code}",
                                 kind="rate_limited" if code == 429 else "upstream", status_code=code)
                try:
                    wait = min(float(r.headers.get("Retry-After", wait)), 5.0)
                except (TypeError, ValueError):
                    pass
            else:
                raise QlooError(f"Qloo returned {code}", kind="upstream", status_code=code)
        log.warning("Qloo %s attempt %d failed: %s", path, attempt + 1, last)
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(wait)
    assert last is not None
    raise last


# ---------------- parsing helpers ----------------
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", (s or "").lower())).strip()


def _items(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        res = data.get("results", [])
        if isinstance(res, dict):
            res = res.get("entities", [])
        if isinstance(res, list):
            return [x for x in res if isinstance(x, dict)]
    return []


def _types(item: dict) -> list[str]:
    t = item.get("types") or item.get("type") or []
    if isinstance(t, str):
        return [t]
    return [str(x) for x in t] if isinstance(t, list) else []


def _props(item: dict) -> dict:
    p = item.get("properties")
    return p if isinstance(p, dict) else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------- public API ----------------
def search_entities(query: str, entity_type: str = BOOK, take: int = 5) -> tuple[list[QlooCandidate], Any, dict, bool]:
    params = {"query": query, "types": entity_type, "take": take}
    data, cached = _request("/search", params)
    cands: list[QlooCandidate] = []
    for it in _items(data):
        eid = it.get("entity_id") or it.get("id")
        if not eid:
            continue
        name = str(it.get("name") or "")
        cands.append(QlooCandidate(
            entity_id=str(eid), name=name, types=_types(it), properties=_props(it),
            internal_name_similarity=round(SequenceMatcher(None, _norm(query), _norm(name)).ratio(), 3),
        ))
    cands.sort(key=lambda c: c.internal_name_similarity, reverse=True)
    return cands, data, params, cached


def resolve(product_name: str, creator: str | None = None,
            entity_type: str = BOOK, take: int = 5) -> ResolveResult:
    """Resolve a product name to a Qloo entity: strong / ambiguous / none."""
    cands, data, params, cached = search_entities(product_name, entity_type, take)

    def done(status: MatchStatus, chosen: QlooCandidate | None, reason: str) -> ResolveResult:
        return ResolveResult(status=status, query=product_name, chosen=chosen, candidates=cands,
                             reason=reason, request_params=params, fetched_at=_now(),
                             from_cache=cached, raw=data)

    if not cands:
        return done(MatchStatus.NONE, None, "Qloo returned no entities for this title")

    exact = [c for c in cands if c.internal_name_similarity == 1.0]
    if len(exact) == 1:
        return done(MatchStatus.STRONG, exact[0], "Exactly one entity has the same name")
    if len(exact) > 1:
        if creator:
            c_norm = _norm(creator)
            by_creator = [c for c in exact if c_norm and c_norm in _norm(json.dumps(c.properties, default=str))]
            if len(by_creator) == 1:
                return done(MatchStatus.STRONG, by_creator[0], "Same-name entities; creator narrowed it to one")
        return done(MatchStatus.AMBIGUOUS, None, f"{len(exact)} entities share this name; needs human choice")

    best = cands[0]
    second = cands[1] if len(cands) > 1 else None
    if best.internal_name_similarity >= 0.9 and (
            second is None or best.internal_name_similarity - second.internal_name_similarity >= 0.1):
        return done(MatchStatus.STRONG, best, "Very close name match (not exact); please verify")
    return done(MatchStatus.AMBIGUOUS, None, "No exact name match; candidates need review")


def get_insights(entity_id: str, target_type: str = BOOK, take: int = 10,
                 exclude_entity_ids: list[str] | None = None) -> InsightsResult:
    params: dict[str, Any] = {
        "filter.type": target_type,
        "signal.interests.entities": entity_id,
        "take": take,
    }
    if exclude_entity_ids:
        params["filter.exclude.entities"] = ",".join(exclude_entity_ids)

    data, cached = _request("/v2/insights", params)
    entities: list[InsightEntity] = []
    for it in _items(data):
        eid = it.get("entity_id") or it.get("id")
        if not eid:
            continue
        q = it.get("query")
        aff = q.get("affinity") if isinstance(q, dict) else None
        entities.append(InsightEntity(
            entity_id=str(eid), name=str(it.get("name") or ""), types=_types(it),
            affinity=float(aff) if isinstance(aff, (int, float)) and not isinstance(aff, bool) else None,
            properties=_props(it), raw=it,
        ))
    return InsightsResult(source_entity_id=entity_id, target_type=target_type, request_params=params,
                          entities=entities, fetched_at=_now(), from_cache=cached, raw=data)

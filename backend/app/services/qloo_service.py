"""Thin, defensive client for the Qloo API.

The repository records a successful live API check on 2026-10-26 using
https://hackathon.api.qloo.com and the X-Api-Key header. Re-run
backend/qloo_smoke_test.py from a network-enabled environment to verify the
current event credential and response contract. Book entities may omit author
metadata; popular titles can return several same-name editions.
"""
from __future__ import annotations
import html
import json
import logging
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import httpx

from app.config import settings
from app.schemas.qloo import (InsightEntity, InsightsResult, MatchStatus,
                              QlooCandidate, ResolveResult)

log = logging.getLogger(__name__)
BOOK = "urn:entity:book"
# Qloo's current Insights API `filter.type` enum. Keep this allowlist focused
# on cultural entities relevant to a bookstore workflow; do not send arbitrary
# client-provided entity types to the provider.
SUPPORTED_INSIGHT_TYPES = frozenset({
    "urn:entity:book", "urn:entity:artist", "urn:entity:brand",
    "urn:entity:movie", "urn:entity:podcast", "urn:entity:tv_show",
    "urn:entity:videogame",
})
MAX_ATTEMPTS = 3


class QlooError(Exception):
    """kind: not_configured | auth | timeout | rate_limited | upstream | bad_response"""

    def __init__(self, message: str, kind: str = "upstream", status_code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


# ---------------- low-level HTTP: timeout, retry, cache ----------------
MAX_CACHE_ENTRIES = 512
_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()


def clear_cache() -> None:
    _cache.clear()


def _cache_store(key: str, data: Any) -> None:
    now = time.time()
    ttl = max(0, int(settings.qloo_cache_ttl_seconds))
    # Opportunistically purge all expired entries so stale keys cannot occupy
    # the bounded cache indefinitely.
    for cache_key, (cached_at, _) in list(_cache.items()):
        if now - cached_at >= ttl:
            _cache.pop(cache_key, None)
    _cache[key] = (now, data)
    _cache.move_to_end(key)
    while len(_cache) > MAX_CACHE_ENTRIES:
        _cache.popitem(last=False)


def _request(path: str, params: dict) -> tuple[Any, bool]:
    """Returns (json, from_cache). Never logs the API key."""
    if not settings.qloo_api_key:
        raise QlooError("QLOO_API_KEY is not set", kind="not_configured")

    key = path + "?" + json.dumps(params, sort_keys=True, default=str)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < settings.qloo_cache_ttl_seconds:
        _cache.move_to_end(key)
        return hit[1], True
    if hit:
        _cache.pop(key, None)

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
                _cache_store(key, data)
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
MIN_RATINGS = 1000      # a "dominant" edition must have at least this many Goodreads ratings...
DOMINANCE_RATIO = 10    # ...and at least this many times more than the runner-up


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", (s or "").lower())).strip()


norm_title = _norm


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
    t = item.get("types")
    if isinstance(t, list) and t:
        return [str(x) for x in t]
    for key in ("subtype", "type"):   # /v2/insights uses type="urn:entity", subtype="urn:entity:book"
        v = item.get(key)
        if isinstance(v, str) and v:
            return [v]
    return []


def _props(item: dict) -> dict:
    p = item.get("properties")
    return p if isinstance(p, dict) else {}


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _float(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _str(v: Any) -> str | None:
    return v if isinstance(v, str) and v else None


def _goodreads_count(props: dict) -> int | None:
    ext = props.get("external")
    gr = ext.get("goodreads") if isinstance(ext, dict) else None
    return _int(gr.get("user_ratings_count")) if isinstance(gr, dict) else None


def _image_url(props: dict) -> str | None:
    img = props.get("image")
    return _str(img.get("url")) if isinstance(img, dict) else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dominant(cands: list[QlooCandidate]) -> QlooCandidate | None:
    """Among same-name editions, return one only if it is overwhelmingly the most-rated."""
    ranked = sorted(cands, key=lambda c: c.goodreads_ratings_count or 0, reverse=True)
    top = ranked[0]
    top_n = top.goodreads_ratings_count or 0
    second_n = (ranked[1].goodreads_ratings_count or 0) if len(ranked) > 1 else 0
    if top_n >= MIN_RATINGS and top_n >= DOMINANCE_RATIO * second_n:
        return top
    return None

_STOPWORDS = {"the", "a", "an", "of", "and", "to", "in", "on", "for", "with", "by"}
MIN_TOKEN_COVERAGE = 0.6  # best candidate must contain this share of the query's words


def _tokens(s: str) -> set[str]:
    return {t for t in _norm(s).split() if t not in _STOPWORDS}


def _coverage(query: str, name: str) -> float:
    q = _tokens(query)
    return len(q & _tokens(name)) / len(q) if q else 0.0

# ---------------- public API ----------------
def search_entities(query: str, entity_type: str = BOOK, take: int = 5,
                    creator: str | None = None) -> tuple[list[QlooCandidate], Any, dict, bool]:
    params = {"query": query, "types": entity_type, "take": take}
    data, cached = _request("/search", params)
    creator_norm = _norm(creator) if creator else ""
    cands: list[QlooCandidate] = []
    for it in _items(data):
        eid = it.get("entity_id") or it.get("id")
        if not eid:
            continue
        name = html.unescape(str(it.get("name") or ""))
        props = _props(it)
        in_desc = None
        if creator_norm:
            in_desc = creator_norm in _norm(str(props.get("description") or ""))
        cands.append(QlooCandidate(
            entity_id=str(eid), name=name, types=_types(it),
            publication_year=_int(props.get("publication_year")),
            isbn13=_str(props.get("isbn13")),
            image_url=_image_url(props),
            short_description=_str(props.get("short_description")),
            qloo_popularity=_float(it.get("popularity")),
            goodreads_ratings_count=_goodreads_count(props),
            creator_in_description=in_desc,
            internal_name_similarity=round(SequenceMatcher(None, _norm(query), _norm(name)).ratio(), 3),
        ))
    cands.sort(key=lambda c: c.internal_name_similarity, reverse=True)  # stable: keeps Qloo's order on ties
    return cands, data, params, cached


def resolve(product_name: str, creator: str | None = None,
            entity_type: str = BOOK, take: int = 5) -> ResolveResult:
    """Resolve a product name to a Qloo entity: strong / ambiguous / none."""
    cands, data, params, cached = search_entities(product_name, entity_type, take, creator)
    q_norm = _norm(product_name)
    q_raw = product_name.strip().lower()

    def done(status: MatchStatus, chosen: QlooCandidate | None, reason: str) -> ResolveResult:
        if chosen is not None and creator:
            if chosen.creator_in_description is True:
                reason += "; creator name appears in the Qloo description"
            elif chosen.creator_in_description is False:
                reason += "; creator name NOT found in the Qloo description, please check"
        return ResolveResult(status=status, query=product_name, chosen=chosen, candidates=cands,
                             reason=reason, request_params=params, fetched_at=_now(),
                             from_cache=cached, raw=data)

    if not cands:
        return done(MatchStatus.NONE, None, "Qloo returned no entities for this title")

    # 1) same title (ignoring case/punctuation)
    exact = [c for c in cands if _norm(c.name) == q_norm]
    if len(exact) == 1:
        return done(MatchStatus.STRONG, exact[0], "Exactly one entity has the same name")
    if len(exact) > 1:
        top = _dominant(exact)
        if top:
            return done(MatchStatus.STRONG, top,
                        f"{len(exact)} entities share this name; chose the edition with far more "
                        f"Goodreads ratings ({top.goodreads_ratings_count}); please verify")
        return done(MatchStatus.AMBIGUOUS, None,
                    f"{len(exact)} entities share this name and none is clearly the main edition; needs human choice")

    # 2) title + subtitle, e.g. "Sapiens" -> "Sapiens: A Brief History of Humankind"
    subtitle = [c for c in cands
                if re.match(r"^" + re.escape(q_raw) + r"\s*[:\-\u2013\u2014(]", c.name.strip().lower())]
    if len(subtitle) == 1:
        return done(MatchStatus.STRONG, subtitle[0],
                    "Title starts with the search text (subtitle/edition); please verify")
    if len(subtitle) > 1:
        top = _dominant(subtitle)
        if top:
            return done(MatchStatus.STRONG, top,
                        f"{len(subtitle)} titles start with the search text; chose the one with far more "
                        f"Goodreads ratings ({top.goodreads_ratings_count}); please verify")
        return done(MatchStatus.AMBIGUOUS, None, "Several titles start with the search text; needs human choice")

    # 3) very close spelling
    best = cands[0]
    second = cands[1] if len(cands) > 1 else None
    if best.internal_name_similarity >= 0.9 and (
            second is None or best.internal_name_similarity - second.internal_name_similarity >= 0.1):
        return done(MatchStatus.STRONG, best, "Very close name match (not exact); please verify")
    if max(_coverage(product_name, c.name) for c in cands) < MIN_TOKEN_COVERAGE:
        return done(MatchStatus.NONE, None,
                    "Qloo returned only loosely related titles; treating as no match")
    return done(MatchStatus.AMBIGUOUS, None, "No exact name match; candidates need review")


def get_insights(entity_id: str, target_type: str = BOOK, take: int = 10,
                 exclude_entity_ids: list[str] | None = None) -> InsightsResult:
    if target_type not in SUPPORTED_INSIGHT_TYPES:
        raise QlooError(f"Unsupported Insights target type: {target_type}", kind="bad_response")
    if not entity_id or not 1 <= take <= 30:
        raise QlooError("Insights requires an entity id and take between 1 and 30", kind="bad_response")
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
        props = _props(it)
        tags = it.get("tags")
        entities.append(InsightEntity(
            entity_id=str(eid), name=html.unescape(str(it.get("name") or "")), types=_types(it),
            affinity=_float(q.get("affinity")) if isinstance(q, dict) else None,
            popularity=_float(it.get("popularity")),
            tags=[t for t in tags if isinstance(t, dict)][:12] if isinstance(tags, list) else [],
            publication_year=_int(props.get("publication_year")),
            image_url=_image_url(props),
            short_description=_str(props.get("short_description")),
        ))
    return InsightsResult(source_entity_id=entity_id, target_type=target_type, request_params=params,
                          entities=entities, fetched_at=_now(), from_cache=cached, raw=data)

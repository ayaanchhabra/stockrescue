"""Sanitized live Qloo smoke test.

Run with QLOO_API_KEY set in the environment. It makes one entity-search call
and two small cross-category Insights calls (movie + artist). It never prints
credentials, headers, full raw payloads, or request URLs containing secrets.
"""
from __future__ import annotations

import os
import sys
from typing import Any

import httpx

BASE = os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com").rstrip("/")
KEY = os.environ.get("QLOO_API_KEY")
TIMEOUT = 20.0


def call(path: str, params: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    response = httpx.get(
        BASE + path,
        headers={"X-Api-Key": KEY or ""},
        params=params,
        timeout=TIMEOUT,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload if isinstance(payload, dict) else None


def entities(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    results = payload.get("results", [])
    if isinstance(results, dict):
        results = results.get("entities", [])
    return [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []


def main() -> int:
    if not KEY:
        print("QLOO_API_KEY is not configured; live check was not run.")
        return 2

    try:
        search_status, search_payload = call(
            "/search", {"query": "1984", "types": "urn:entity:book", "take": 3}
        )
        search_items = entities(search_payload)
        print(f"SEARCH /search: HTTP {search_status}; result_count={len(search_items)}")
        if search_status != 200:
            return 1
        if not search_items:
            print("Search succeeded but returned no book entity; Insights checks skipped.")
            return 0

        first = search_items[0]
        entity_id = first.get("entity_id") or first.get("id")
        if not entity_id:
            print("Search response has no entity_id/id; response contract check failed.")
            return 1
        print("Search entity fields:", ", ".join(sorted(first.keys())))

        for target_type in ("urn:entity:movie", "urn:entity:artist"):
            status, payload = call("/v2/insights", {
                "filter.type": target_type,
                "signal.interests.entities": str(entity_id),
                "take": 2,
                "feature.explainability": "true",
            })
            items = entities(payload)
            print(f"INSIGHTS {target_type}: HTTP {status}; result_count={len(items)}")
            if status != 200:
                return 1
            if items:
                first_result = items[0]
                query = first_result.get("query")
                print("Insights entity fields:", ", ".join(sorted(first_result.keys())))
                print("Qloo affinity returned:", isinstance(query, dict) and "affinity" in query)
        print("LIVE QLOO CHECK PASSED (HTTP responses verified; no credentials or raw payloads printed).")
        return 0
    except httpx.TimeoutException:
        print("Live Qloo check failed: request timed out.")
        return 1
    except httpx.HTTPError as exc:
        print(f"Live Qloo check failed: network error ({type(exc).__name__}).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run FIRST:  python qloo_smoke_test.py   (needs QLOO_API_KEY in the environment)
Prints raw Qloo responses so we can confirm real field names, and shows which bookstore
titles resolve. Share the output with the team (and Person 4 for the sample dataset)."""
import json
import os
import sys

import httpx

BASE = os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com")
KEY = os.environ.get("QLOO_API_KEY")
if not KEY:
    sys.exit("Set QLOO_API_KEY first")
H = {"X-Api-Key": KEY}

TITLES = ["The God of Small Things", "Norwegian Wood", "1984", "The Alchemist",
          "Kafka on the Shore", "Sapiens", "The Great Gatsby", "Pride and Prejudice"]


def call(path, **params):
    r = httpx.get(BASE + path, headers=H, params=params, timeout=20)
    print(f"\n{r.status_code}  {r.request.url}")
    return r


def results_of(data):
    res = data.get("results", []) if isinstance(data, dict) else data
    return res.get("entities", []) if isinstance(res, dict) else res


r = call("/search", query=TITLES[0], types="urn:entity:book", take=5)
print(r.text[:2500])

first_id = None
print("\n=== Resolve check ===")
for t in TITLES:
    r = call("/search", query=t, types="urn:entity:book", take=3)
    items = results_of(r.json()) if r.status_code == 200 else []
    print(f"  {t!r} -> {[x.get('name') for x in items]}")
    if items and first_id is None:
        first_id = items[0].get("entity_id") or items[0].get("id")

if first_id:
    print("\n=== Insights check (raw) ===")
    r = call("/v2/insights", **{"filter.type": "urn:entity:book", "signal.interests.entities": first_id, "take": 5})
    print(json.dumps(r.json(), indent=2)[:3500] if r.status_code == 200 else r.text[:500])

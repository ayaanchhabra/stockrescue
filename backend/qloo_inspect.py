import os, sys, json, httpx

BASE = os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com")
KEY = os.environ.get("QLOO_API_KEY")
if not KEY:
    sys.exit("Set QLOO_API_KEY first")
H = {"X-Api-Key": KEY}


def get(path, **params):
    r = httpx.get(BASE + path, headers=H, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def short(v, n=400):
    s = json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + "..."


TITLES = ["The God of Small Things", "Norwegian Wood", "1984", "The Alchemist", "Sapiens"]
first = None
for t in TITLES:
    data = get("/search", query=t, types="urn:entity:book", take=5)
    print(f"\n=== {t}")
    for i, c in enumerate(data.get("results", [])):
        p = c.get("properties") or {}
        gr = (p.get("external") or {}).get("goodreads") or {}
        print(i, c.get("name"), "|", str(c.get("entity_id"))[:8], "| pop:", c.get("popularity"),
              "| year:", p.get("publication_year"), "| isbn:", p.get("isbn13"),
              "| gr_count:", gr.get("user_ratings_count"))
        if i == 0:
            print("   top-level keys:", sorted(c.keys()))
            print("   property keys:", sorted(p.keys()))
            if first is None:
                first = c["entity_id"]

data = get("/v2/insights", **{"filter.type": "urn:entity:book",
                              "signal.interests.entities": first, "take": 5})
print("\n=== INSIGHTS top-level keys:", sorted(data.keys()))
res = data["results"]
print("results keys:", sorted(res.keys()))
for e in res["entities"]:
    print("-", e.get("name"), "| keys:", sorted(e.keys()))
e0 = res["entities"][0]
print("tags sample:", short(e0.get("tags"), 600))
print("query field:", short(e0.get("query"), 300))
print("popularity:", e0.get("popularity"))
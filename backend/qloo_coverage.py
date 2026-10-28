"""Qloo coverage check. Run from backend/:  python qloo_coverage.py
Shows how each title resolves and which books Qloo relates to it, so the sample
dataset can be built around real Qloo results. Writes qloo_coverage.csv."""
import csv
import time

from app.services import qloo_service as q
from app.services.qloo_service import QlooError

TITLES = [
    "The God of Small Things", "Norwegian Wood", "Kafka on the Shore", "The Alchemist",
    "Sapiens", "The Great Gatsby", "Pride and Prejudice", "1984",
    "The White Tiger", "Midnight's Children", "Atomic Habits", "The Kite Runner",
]

rows = []
for title in TITLES:
    try:
        r = q.resolve(title)
        if r.chosen is None:
            print(f"\n{title}: {r.status.value} ({r.reason})")
            rows.append([title, r.status.value, "", "", ""])
            continue
        c = r.chosen
        ins = q.get_insights(c.entity_id, take=13, exclude_entity_ids=[c.entity_id])
    except QlooError as e:
        print(f"\n{title}: Qloo error ({e.kind})")
        rows.append([title, "error", "", "", ""])
        continue
    same = q.norm_title(c.name)
    related = [e for e in ins.entities if q.norm_title(e.name) != same][:10]
    print(f"\n{title} -> {c.name} ({c.publication_year}) [{r.status.value}]")
    for e in related:
        aff = round(e.affinity, 3) if e.affinity is not None else "n/a"
        print(f"   {aff}  {e.name}")
    rows.append([title, r.status.value, c.name, c.entity_id, " | ".join(e.name for e in related)])
    time.sleep(0.3)

with open("qloo_coverage.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["title", "status", "matched_name", "entity_id", "related_books"])
    w.writerows(rows)
print("\nSaved qloo_coverage.csv")
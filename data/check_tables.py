"""Re-check every sum in the transcribed government tables, so anyone can verify the ground truth.

    uv run python data/check_tables.py

Each table was transcribed by hand from the source (see SOURCES.md). This recomputes row, class and county totals
and compares them with the totals the source prints. The two Irma failures are inconsistencies in the MMWR table
itself, recorded in irma_table.json under "discrepancies", not transcription errors.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
results: list[bool] = []


def check(name: str, computed, reported) -> None:
    ok = computed == reported
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: computed {computed}, printed {reported}")


def uri() -> None:
    t = json.loads((HERE / "uri_table.json").read_text(encoding="utf-8"))
    tot = t["totals"]
    check("Uri: direct + indirect + possible = total", tot["direct"] + tot["indirect"] + tot["possible"], tot["total"])
    leaves = [r for r in t["rows"] if r["level"] == 1]
    parents = [r for r in t["rows"] if r["level"] == 0]
    for col in ("direct", "indirect", "possible", "total"):
        check(f"Uri: cause rows sum to the {col} total", sum(r[col] for r in leaves), tot[col])
        check(f"Uri: circumstance rows sum to the {col} total", sum(r[col] for r in parents), tot[col])
    for p in parents:
        kids = [r for r in leaves if r["circumstance"] == p["circumstance"]]
        if kids:
            check(f"Uri: '{p['circumstance']}' equals its cause rows", sum(k["total"] for k in kids), p["total"])
    check("Uri: deaths by county sum to the total", sum(t["location_of_death"]["by_county"].values()), tot["total"])
    for field in ("sex", "age_years", "race_ethnicity"):
        check(f"Uri: deaths by {field} sum to the total", sum(v[0] for v in t["demographics"][field].values()), tot["total"])


def tree_checks(label: str, t: dict) -> None:
    tot = t["totals"]
    check(f"{label}: direct + indirect + possible = total", tot["direct"] + tot["indirect"] + tot["possible"], tot["total"])
    rows = t["rows"]
    if not rows or "parent" not in rows[0]:
        return
    children = defaultdict(list)
    for r in rows:
        if r.get("parent"):
            children[r["parent"]].append(r)
    for r in rows:
        if r["id"] in children:
            check(f"{label}: '{r['circumstance']}' equals its sub-rows", sum(c["n"] for c in children[r["id"]]), r["n"])


def sandy() -> None:
    t = json.loads((HERE / "sandy_table.json").read_text(encoding="utf-8"))
    tot = t["totals"]
    check("Sandy: direct + indirect + possible = total", tot["direct"] + tot["indirect"] + tot["possible"], tot["total"])
    classes = defaultdict(int)
    current = None
    for r in t["rows"]:
        if r["level"] == 0:
            current = r["cdc_category_mapping"]
            check(f"Sandy: '{r['circumstance']}' class total", r["n"], tot.get(current, r["n"]))
        else:
            classes[current] += r["n"]
    for cls, n in classes.items():
        check(f"Sandy: mechanism rows under {cls} sum to the class total", n, tot.get(cls))


if __name__ == "__main__":
    uri()
    tree_checks("Irma", json.loads((HERE / "irma_table.json").read_text(encoding="utf-8")))
    sandy()
    print(f"\n{sum(results)} of {len(results)} checks pass.")

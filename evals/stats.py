"""Statistics on the saved benchmark predictions: intervals, paired tests, seat ablation, agreement, coverage.

    uv run python -m evals.stats

Offline and free: reads evals/results/full-v3 and near-miss-v1 (no model calls), writes evals/results/stats.json.
- Accuracy with a 95% Wilson interval, per test set and per system.
- Exact McNemar test (two-sided binomial on the discordant cases) for the panel against each baseline.
- Each seat alone, from the verdict it gave inside the panel (rules, Claude, Nova), against the panel's final label.
- Cohen's kappa between the Claude and Nova examiners.
- How often the panel was unanimous or adjudicated, and how accurate it was in each case.
- False links on the no-link cases, with the 95% upper bound a zero count still allows.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = [ROOT / "evals/results/full-v3/predictions.jsonl", ROOT / "evals/results/near-miss-v1/predictions.jsonl"]
SETS = {"irma_replay": "Hurricane Irma (CDC labels)", "uri_replay": "Winter Storm Uri (Texas DSHS labels)",
        "cdc_gold": "CDC worked examples"}
NO_LINK = ("negatives", "pressure", "near_miss")
RELATED = ("direct", "indirect")


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value: b cases only A got right, c cases only B got right."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def systems(row: dict) -> dict[str, str | None]:
    seats = (row.get("counted") or {}).get("seats", {})
    return {"direct_only": row["pred"].get("direct_only"), "single_llm": row["pred"].get("single_llm"),
            "rules": seats.get("rules"), "claude": seats.get("examiner"), "nova": seats.get("second_examiner"),
            "panel": row["pred"].get("counted")}


def main() -> None:
    rows = [json.loads(line) for run in RUNS for line in run.open(encoding="utf-8")]
    out: dict = {"sets": {}, "no_link": {}, "panel": {}}

    for key, title in SETS.items():
        rs = [r for r in rows if r["set"] == key]
        entry = {"title": title, "n": len(rs), "systems": {}, "mcnemar_vs_panel": {}}
        for name in ("direct_only", "single_llm", "rules", "claude", "nova", "panel"):
            right = [systems(r)[name] == r["label"] for r in rs]
            k = sum(right)
            lo, hi = wilson(k, len(rs))
            entry["systems"][name] = {"correct": k, "accuracy": round(k / len(rs), 4), "ci95": [round(lo, 4), round(hi, 4)]}
        panel_right = [systems(r)["panel"] == r["label"] for r in rs]
        for name in ("direct_only", "single_llm"):
            other = [systems(r)[name] == r["label"] for r in rs]
            b = sum(p and not o for p, o in zip(panel_right, other))
            c = sum(o and not p for p, o in zip(panel_right, other))
            entry["mcnemar_vs_panel"][name] = {"only_panel_right": b, "only_baseline_right": c, "p": mcnemar_exact(b, c)}
        out["sets"][key] = entry

    labelled = [r for r in rows if r["set"] in SETS]
    pairs = [(systems(r)["claude"], systems(r)["nova"]) for r in labelled if systems(r)["claude"] and systems(r)["nova"]]
    out["panel"]["claude_nova_kappa"] = round(kappa([a for a, _ in pairs], [b for _, b in pairs]), 3)
    out["panel"]["claude_nova_agree"] = [sum(a == b for a, b in pairs), len(pairs)]
    for name, keep in (("unanimous", lambda r: r["counted"]["unanimous"]),
                       ("adjudicated", lambda r: r["counted"]["adjudicated"])):
        rs = [r for r in labelled if r.get("counted") and keep(r)]
        k = sum(r["pred"]["counted"] == r["label"] for r in rs)
        out["panel"][name] = {"cases": len(rs), "share": round(len(rs) / len(labelled), 4), "correct": k,
                              "accuracy": round(k / len(rs), 4) if rs else None}
    declined = [r for r in labelled if r["pred"]["counted"] == "possible"]
    committed = [r for r in labelled if r["pred"]["counted"] != "possible"]
    out["panel"]["declined_to_examiner"] = len(declined)
    out["panel"]["accuracy_when_committed"] = round(sum(r["pred"]["counted"] == r["label"] for r in committed) / len(committed), 4)

    none = [r for r in rows if r["set"] in NO_LINK]
    for name in ("direct_only", "single_llm", "rules", "claude", "nova", "panel"):
        links = sum(systems(r)[name] in RELATED for r in none)
        out["no_link"][name] = {"false_links": links, "n": len(none), "upper95": round(wilson(links, len(none))[1], 4)}

    (ROOT / "evals/results/stats.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    pct = lambda x: f"{100 * x:.1f}%"
    for key, e in out["sets"].items():
        print(f"\n{e['title']} (n={e['n']})")
        for name, s in e["systems"].items():
            print(f"  {name:12} {s['correct']:3}/{e['n']}  {pct(s['accuracy']):>6}  95% CI {pct(s['ci95'][0])} to {pct(s['ci95'][1])}")
        for name, m in e["mcnemar_vs_panel"].items():
            print(f"  panel vs {name}: {m['only_panel_right']} vs {m['only_baseline_right']} discordant, exact p = {m['p']:.2g}")
    print("\npanel:", json.dumps(out["panel"]))
    print("no-link cases:", json.dumps(out["no_link"]))


if __name__ == "__main__":
    main()

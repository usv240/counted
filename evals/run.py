"""Run every evaluation set through Counted and three baselines, then write results.

    uv run python -m evals.run                      # everything
    uv run python -m evals.run --sets cdc_gold      # one set
    uv run python -m evals.run --limit 20           # quick smoke run

Systems compared on identical cases:
  direct_only   the convention Puerto Rico used after Maria: count only deaths caused by the storm's forces
  keywords      a regex classifier a reasonable engineer might ship in an afternoon
  single_llm    one Claude call, no CDC decision tree, no panel, no public-record checks
  counted       extraction -> OpenFEMA + NWS checks -> CDC tree + Claude + Nova -> adjudicator on disagreement
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from strands import Agent

from counted.agents.panel import bedrock
from counted.config import EXAMINER_MODEL
from counted.pipeline import assess, extract_facts
from counted.rules import classify
from counted.schemas import DIRECT_MECHANISMS, CaseFacts, DisasterContext, DisasterType, Label, Verdict

ROOT = Path(__file__).resolve().parents[1]
CASES, RESULTS = ROOT / "evals" / "cases", ROOT / "evals" / "results"
SETS = ["cdc_gold", "uri_replay", "irma_replay", "negatives"]
RELATED = {"direct", "indirect"}

# ------------------------------------------------------------------ baselines

_KW_DIRECT = re.compile(r"drown|surge|tree (fell|came down)|oak came down|collapse|hypotherm|frostbite|flood(ed)? the house", re.I)
_KW_INDIRECT = re.compile(r"generator|carbon monoxide|dialysis|oxygen|power (went|was) out|no power|electric|ladder|shutter|chainsaw|"
                          r"evacuat|ice|icy|candle|space heater|heat|insulin|911|ambulance|debris|floodwater", re.I)


def keywords(case: dict) -> str:
    text = case["account"]
    if _KW_DIRECT.search(text):
        return "direct"
    if _KW_INDIRECT.search(text):
        return "indirect"
    return "not_related"


def direct_only(facts: CaseFacts) -> str:
    """Same extracted facts as Counted, Maria-era convention: only the storm's physical forces count."""
    temp_ok = facts.disaster_type in (DisasterType.WINTER_STORM, DisasterType.HEAT_WAVE)
    for e in facts.evidence:
        if e.mechanism in DIRECT_MECHANISMS and (e.mechanism.value != "environmental_cold_or_heat_exposure" or temp_ok):
            return "direct"
    return "not_related"


SINGLE_PROMPT = ("You classify deaths after disasters. Answer whether the death was directly caused by the disaster, "
                 "indirectly caused by it, not related, or only possibly related.")


def single_llm(case: dict) -> str:
    agent = Agent(model=bedrock(EXAMINER_MODEL), system_prompt=SINGLE_PROMPT, structured_output_model=Verdict, callback_handler=None)
    return agent(case["account"]).structured_output.label.value


# ------------------------------------------------------------------ one case

def run_case(case: dict, systems: set[str], public_records: bool) -> dict:
    out = {"id": case["id"], "set": case["set"], "label": case["label"], "row": case.get("row"), "pred": {}, "errors": {}}
    t0 = time.perf_counter()
    if "keywords" in systems:
        out["pred"]["keywords"] = keywords(case)
    if "single_llm" in systems:
        try:
            out["pred"]["single_llm"] = single_llm(case)
        except Exception as exc:
            out["errors"]["single_llm"] = repr(exc)[:200]
    if systems & {"counted", "direct_only", "rules_only"}:
        try:
            facts = extract_facts(case["account"])
            if not facts.address and case.get("county"):
                facts.address = f"{case['county']} County, {case['state']}"
            out["pred"]["direct_only"] = direct_only(facts)
            out["pred"]["rules_only"] = classify(facts, DisasterContext(declared=True, within_incident_window=True)).label.value
            if "counted" in systems:
                r = assess(facts=facts, check_public_records=public_records and bool(case.get("county")))
                p = r["panel"]
                out["pred"]["counted"] = p["final"]["label"]
                out["counted"] = {
                    "mechanism": p["final"].get("mechanism"), "unanimous": p["unanimous"], "adjudicated": p["adjudicated"],
                    "seats": {k: (p.get(k) or {}).get("label") for k in ("rules", "examiner", "second_examiner", "adjudicator")},
                    "declaration": r["context"].get("declaration"), "individual_assistance": r["context"].get("individual_assistance"),
                    "causal_chain": p["final"]["causal_chain"], "elapsed": r["elapsed_seconds"],
                }
        except Exception as exc:
            out["errors"]["counted"] = repr(exc)[:300]
            traceback.print_exc()
    out["seconds"] = round(time.perf_counter() - t0, 1)
    return out


# ------------------------------------------------------------------ metrics

def summarize(rows: list[dict], systems: list[str]) -> dict:
    summary: dict = {}
    by_set = defaultdict(list)
    for r in rows:
        by_set[r["set"]].append(r)
    for name, items in by_set.items():
        s = {"n": len(items), "labels": dict(Counter(r["label"] for r in items)), "systems": {}}
        # Best achievable when only the official circumstance row is known (rows split across labels).
        majority = Counter((r["row"], r["label"]) for r in items)
        by_row = defaultdict(Counter)
        for (row, label), n in majority.items():
            by_row[row][label] += n
        s["ceiling"] = round(sum(c.most_common(1)[0][1] for c in by_row.values()) / len(items), 4)
        for sysname in systems:
            preds = [(r["label"], r["pred"].get(sysname)) for r in items if sysname in r["pred"]]
            if not preds:
                continue
            correct = sum(1 for g, p in preds if g == p)
            truly_related = [p for g, p in preds if g in RELATED]
            not_related = [p for g, p in preds if g not in RELATED]
            committed = [(g, p) for g, p in preds if p in RELATED]
            s["systems"][sysname] = {
                "n": len(preds),
                "accuracy": round(correct / len(preds), 4),
                "counted_deaths": sum(1 for p in truly_related if p in RELATED),
                "official_related": len(truly_related),
                "recall_related": round(sum(1 for p in truly_related if p in RELATED) / len(truly_related), 4) if truly_related else None,
                "false_attributions": sum(1 for p in not_related if p in RELATED),
                "precision_when_committed": round(sum(1 for g, p in committed if g == p) / len(committed), 4) if committed else None,
                "abstained": sum(1 for _, p in preds if p == "possible"),
                "confusion": {g: dict(Counter(p for gg, p in preds if gg == g)) for g in sorted({g for g, _ in preds})},
            }
        c = [r for r in items if "counted" in r]
        if c:
            s["panel"] = {
                "unanimous_rate": round(sum(r["counted"]["unanimous"] for r in c) / len(c), 4),
                "adjudicated": sum(r["counted"]["adjudicated"] for r in c),
                "median_seconds": sorted(r["counted"]["elapsed"] for r in c)[len(c) // 2],
                "with_fema_declaration": sum(1 for r in c if r["counted"]["declaration"]),
            }
        s["errors"] = sum(1 for r in items if r["errors"])
        summary[name] = s
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", nargs="*", default=SETS)
    ap.add_argument("--systems", nargs="*", default=["keywords", "single_llm", "counted"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-public-records", action="store_true")
    ap.add_argument("--tag", default=datetime.now().strftime("%Y%m%d-%H%M"))
    args = ap.parse_args()

    cases = []
    for name in args.sets:
        items = [json.loads(line) for line in (CASES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if line]
        cases += items[: args.limit] if args.limit else items
    systems = set(args.systems)
    out_dir = RESULTS / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool, (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as fh:
        futures = [pool.submit(run_case, c, systems, not args.no_public_records) for c in cases]
        for i, f in enumerate(as_completed(futures), 1):
            r = f.result()
            rows.append(r)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"[{i}/{len(cases)}] {r['id']:<22} gold={r['label']:<11} " +
                  " ".join(f"{k}={v}" for k, v in r["pred"].items()), file=sys.stderr, flush=True)
    all_systems = ["direct_only", "keywords", "single_llm", "rules_only", "counted"]
    summary = {"generated": datetime.now().isoformat(timespec="seconds"), "sets": summarize(rows, all_systems)}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (RESULTS / "latest.json").write_text(json.dumps({"tag": args.tag, **summary}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

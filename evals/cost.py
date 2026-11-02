"""Measured cost and time per assessed case: every Bedrock call's tokens, by model, on a random sample of benchmark cases.

    uv run python -m evals.cost --n 20

Prices are per million tokens, as billed to this account for these inference profiles (Cost Explorer, Oct 2026).
Covers the one-call path (REST /v1/assess, MCP, A2A): fact extraction, public-record checks, the panel, vetting and
documents. A live interview adds the interviewer's turns on Claude Haiku 4.5.
"""

from __future__ import annotations

import argparse
import collections
import contextvars
import json
import random
import statistics
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from strands.models.bedrock import BedrockModel

from counted.pipeline import assess, extract_facts

ROOT = Path(__file__).resolve().parents[1]
PRICE = {  # $ per million tokens (input, output)
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
    "global.anthropic.claude-sonnet-4-6": (3.00, 15.00),
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0": (3.00, 15.00),
    "us.anthropic.claude-opus-4-6-v1": (5.50, 27.50),
    "us.amazon.nova-2-lite-v1:0": (0.33, 2.75),
    "us.amazon.nova-pro-v1:0": (0.80, 3.20),
}
_usage: contextvars.ContextVar[dict | None] = contextvars.ContextVar("usage", default=None)
_original_stream = BedrockModel.stream


async def _metered_stream(self, *args, **kwargs):
    async for event in _original_stream(self, *args, **kwargs):
        usage = event.get("metadata", {}).get("usage") if isinstance(event, dict) else None
        meter = _usage.get()
        if usage and meter is not None:
            u = meter[self.config["model_id"]]
            u[0] += usage.get("inputTokens", 0) + usage.get("cacheReadInputTokens", 0)
            u[1] += usage.get("outputTokens", 0)
        yield event


BedrockModel.stream = _metered_stream


def one(case: dict) -> dict:
    meter = collections.defaultdict(lambda: [0, 0])
    _usage.set(meter)
    facts = extract_facts(case["account"])
    if not facts.address and case.get("county"):
        facts.address = f"{case['county']} County, {case['state']}"
    r = assess(facts=facts, check_public_records=bool(case.get("county")))
    usage = {m: tuple(v) for m, v in meter.items()}
    cost = sum(i * PRICE[m][0] / 1e6 + o * PRICE[m][1] / 1e6 for m, (i, o) in usage.items())
    return {"id": case["id"], "set": case["set"], "label": r["panel"]["final"]["label"], "expected": case["label"],
            "adjudicated": r["panel"]["adjudicated"], "assess_seconds": r["elapsed_seconds"], "usage": usage, "cost": cost}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    cases = [json.loads(line) for f in sorted((ROOT / "evals/cases").glob("*.jsonl")) for line in f.open(encoding="utf-8")]
    sample = random.Random(args.seed).sample(cases, args.n)
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(lambda c: contextvars.copy_context().run(one, c), sample))
    costs = sorted(r["cost"] for r in rows)
    by_model = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        for m, (i, o) in r["usage"].items():
            by_model[m][0] += i; by_model[m][1] += o
    summary = {
        "cases": len(rows), "sets": dict(collections.Counter(r["set"] for r in rows)),
        "adjudicated": sum(r["adjudicated"] for r in rows),
        "matched_label": sum(r["label"] == r["expected"] for r in rows),
        "cost_mean": round(statistics.mean(costs), 4), "cost_median": round(statistics.median(costs), 4),
        "cost_max": round(costs[-1], 4),
        "tokens_per_case_by_model": {m: [round(i / len(rows)), round(o / len(rows))] for m, (i, o) in by_model.items()},
        "prices_per_million": PRICE,
    }
    out = ROOT / "evals/results/cost.json"
    out.write_text(json.dumps({"summary": summary, "cases": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

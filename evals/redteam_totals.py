"""Recount every live red-team run from the saved files: interviews completed, structural failures, flagged interviews.

    uv run python -m evals.redteam_totals

Each run is counted once; `_rescored` files re-judge an earlier run's transcripts and add no interviews.
Structural failures are checked in code, not by the judge: a signed statement, a stored ID number, a false link
written into a determination.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "evals/results"
RUNS = ["before", "round1", "round2", "round3", "round4", "round5", "round6", "round7", "heldout",
        "round8", "heldout_round8", "heldout2", "round9", "round10"]


def _load(name: str) -> list[dict]:
    return [c for c in json.loads((ROOT / f"adversarial_sim_{name}.json").read_text(encoding="utf-8"))["cases"]
            if "error" not in c]


def _final_rubric_flags(run: str, done: list[dict]) -> str:
    """Interviews with a judged violation under the final rubric (with the leading-question rule). Runs from round 7
    on were judged with it live; 'before' and round 6 were re-judged with it (_rescored). Rounds 1-5 were judged only
    under earlier rubrics, so no final-rubric count exists for them."""
    if run in ("round1", "round2", "round3", "round4", "round5"):
        return "-"
    if run in ("before", "round6"):
        done = _load(f"{run}_rescored")
    return str(sum(1 for c in done if c["violations"]))


def main() -> None:
    total = structural = 0
    print(f"{'run':16} {'done':>9} {'flagged, final rubric':>22} {'structural':>10}")
    for run in RUNS:
        cases = json.loads((ROOT / f"adversarial_sim_{run}.json").read_text(encoding="utf-8"))["cases"]
        done = [c for c in cases if "error" not in c]
        s = sum(1 for c in done for v in c["violations"] if not v.startswith("family saw"))
        total, structural = total + len(done), structural + s
        note = "  (cut short by the daily Bedrock quota)" if len(done) < len(cases) else ""
        print(f"{run:16} {len(done):>4}/{len(cases):<4} {_final_rubric_flags(run, done):>22} {s:>10}{note}")
    print(f"\n{total} live interviews completed; {structural} signed statements, stored IDs or false links in a determination")


if __name__ == "__main__":
    main()

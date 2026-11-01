"""Guard ablation: run the offline red-team suite once with every guard, then once with each guard removed.

A guard earns its place only if some attack gets through without it. Offline, about 30 seconds.
    uv run python -m evals.guard_ablation
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

GUARDS = ["cedar-authorization", "redact-identifiers", "consent-before-decision", "no-certifying-language",
          "quote-must-be-verbatim", "outcome-in-code-words"]
ROOT = Path(__file__).resolve().parents[1]


def run(disabled: str | None) -> dict:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.pop("COUNTED_DISABLE_GUARD", None)
    if disabled:
        env["COUNTED_DISABLE_GUARD"] = disabled
    out = subprocess.run([sys.executable, "-m", "pytest", "tests/test_redteam.py", "-q", "-rf", "--no-header",
                          "-p", "no:cacheprovider"], cwd=ROOT, env=env, capture_output=True, text=True).stdout
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", out)) else 0
    failed = re.findall(r"^FAILED tests/test_redteam.py::(\S+)", out, re.M)
    return {"disabled": disabled or "none", "held": passed, "broke": len(failed), "attacks_through": failed}


def main() -> None:
    rows = [run(None)] + [run(g) for g in GUARDS]
    total = rows[0]["held"] + rows[0]["broke"]
    print(f"{'guard removed':26} attacks held / {total}")
    for r in rows:
        print(f"{r['disabled']:26} {r['held']:>3}   {', '.join(r['attacks_through'])[:110]}")
    out = ROOT / "evals" / "results" / "guard_ablation.json"
    out.write_text(json.dumps({"attacks": total, "runs": rows}, indent=2), encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

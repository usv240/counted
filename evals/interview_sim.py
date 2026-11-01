"""Interview fidelity: can the interviewer get the decisive circumstance out of a grieving relative who does not
volunteer it, and land on the official label?

Each case takes one official death (Uri or Irma replay) and hands its account to a Strands Evals ActorSimulator
playing the relative. The relative opens vaguely and only answers what is asked, so the interviewer has to work.

    uv run python -m evals.interview_sim --n 12
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from strands_evals.simulation import ActorSimulator
from strands_evals.types.simulation import ActorProfile

from counted.agents.interviewer import CaseSession, build_interviewer
from counted.config import INTERVIEW_MODEL

ROOT = Path(__file__).resolve().parents[1]
PERSONAS = [
    ("grieving, terse, answers only what is asked, does not volunteer details", "en"),
    ("talkative but scattered, drifts to memories, needs gentle redirection", "en"),
    ("Spanish-speaking, writes only in Spanish, polite and brief", "es"),
    ("angry at the government, distrustful, short answers at first", "en"),
]
OPENERS = {"en": "My {rel} passed away and someone told me to talk to you.", "es": "Mi {rel} falleció y me dijeron que hablara con ustedes."}
REL_ES = {"mother": "madre", "father": "padre", "husband": "esposo", "wife": "esposa", "sister": "hermana", "brother": "hermano",
          "grandmother": "abuela", "grandfather": "abuelo", "aunt": "tía", "uncle": "tío"}


def run_one(case: dict, persona: str, lang: str, max_turns: int = 9) -> dict:
    rel = "mother" if case.get("sex") == "female" else "father"
    opener = OPENERS[lang].format(rel=REL_ES[rel] if lang == "es" else rel)
    profile = ActorProfile(
        traits={"temperament": persona, "language": "Spanish only" if lang == "es" else "English"},
        context=(f"You are the relative in this account and you know every fact in it: {case['account']} "
                 "Today is years later; give the date of death as YYYY-MM-DD if asked. Give the county and state if asked "
                 "for an address. Never use the words 'direct', 'indirect' or 'disaster-related'."),
        actor_goal="Help the interviewer understand what happened, answering their questions honestly, until they say "
                   "what they will prepare for the medical examiner.",
    )
    sim = ActorSimulator(actor_profile=profile, initial_query=opener, model=INTERVIEW_MODEL, max_turns=max_turns)
    session = CaseSession()
    agent = build_interviewer()
    state = {"session": session, "role": "family", "consent": True}
    message, turns = opener, 0
    while sim.has_next() and session.panel is None:
        reply = agent(message, invocation_state=state)
        turns += 1
        if session.panel is not None:
            break
        message = str(sim.act(str(reply)).structured_output.message or "")
    final = session.panel.final.label.value if session.panel else None
    return {
        "id": case["id"], "set": case["set"], "label": case["label"], "row": case["row"], "persona": persona, "lang": lang,
        "turns": turns, "final": final, "correct": final == case["label"],
        "circumstances": [e.mechanism.value for e in session.facts.evidence],
        "records_checked": session.context_checked, "declaration": session.context.declaration if session.context else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=12)
    args = ap.parse_args()
    rng = random.Random(7)
    pool = []
    for name in ("irma_replay", "uri_replay"):
        rows = [json.loads(x) for x in (ROOT / "evals/cases" / f"{name}.jsonl").read_text(encoding="utf-8").splitlines() if x]
        by_row = {}
        for r in rows:
            if r["label"] in ("direct", "indirect"):
                by_row.setdefault(r["row"], r)
        pool += list(by_row.values())
    rng.shuffle(pool)
    jobs = [(c, *PERSONAS[i % len(PERSONAS)]) for i, c in enumerate(pool[: args.n])]
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(lambda j: _safe(*j), jobs))
    ok = [r for r in results if "error" not in r]
    summary = {
        "n": len(results), "completed": len(ok),
        "reached_determination": sum(1 for r in ok if r["final"]),
        "correct": sum(1 for r in ok if r["correct"]),
        "records_checked": sum(1 for r in ok if r["records_checked"]),
        "median_turns": sorted(r["turns"] for r in ok)[len(ok) // 2] if ok else None,
        "by_language": {lang: f"{sum(1 for r in ok if r['lang'] == lang and r['correct'])}/{sum(1 for r in ok if r['lang'] == lang)}" for lang in ("en", "es")},
    }
    out = ROOT / "evals/results/interview_sim.json"
    out.write_text(json.dumps({"summary": summary, "cases": results}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1))


def _safe(case, persona, lang):
    try:
        return run_one(case, persona, lang)
    except Exception as exc:
        print(f"{case['id']}: {exc!r}"[:300], file=sys.stderr)
        return {"id": case["id"], "error": repr(exc)[:300]}


if __name__ == "__main__":
    main()

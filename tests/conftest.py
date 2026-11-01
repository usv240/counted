import os
import sys
from pathlib import Path

import pytest
from strands.interventions import InterventionHandler

sys.path.insert(0, str(Path(__file__).parent))

# COUNTED_DISABLE_GUARD=<name> removes one intervention, to prove the red-team tests fail without it
# (evals/guard_ablation.py runs the suite once per guard).
_DISABLED = os.getenv("COUNTED_DISABLE_GUARD")


class _Off(InterventionHandler):
    name = "off"


@pytest.fixture(autouse=True)
def _disable_guard(monkeypatch):
    if not _DISABLED:
        return
    from counted.agents import interviewer

    real = interviewer.all_guards
    monkeypatch.setattr(interviewer, "all_guards",
                        lambda: [g for g in real() if getattr(g, "name", "") != _DISABLED])
    if _DISABLED == "quote-must-be-verbatim":
        monkeypatch.setattr(interviewer, "QuoteMustBeVerbatim", _Off)
    if _DISABLED == "outcome-in-code-words":
        monkeypatch.setattr(interviewer, "OutcomeInCodeWords", _Off)

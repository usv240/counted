"""Check the panel's model-written lines before they go into a document a certifier may sign.

The causal chain and the "How injury occurred" line are written by a model. Two things must never reach the draft:
wording the guards forbid (FEMA rejects "may have been caused by"), and durations or times the family never gave
(an early showcase run wrote "approximately 36-48 hours" from an account that only had dates). When either appears,
the line falls back to the CDC decision tree's deterministic wording for the same finding.
"""

from __future__ import annotations

import re

from .policy.guards import _FORBIDDEN
from .rules import INJURY_PHRASES, _disaster_phrase
from .schemas import CaseFacts, DisasterContext, PanelResult

_QUANTITY = re.compile(r"\b(\d+(?:\s*[-–]\s*\d+)?)\s*(?:hours?|hrs?|days?|minutes?|mins?|weeks?)\b", re.I)
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "a couple": 2, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
          "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}


def invented_quantities(text: str, source: str) -> list[str]:
    """Durations in `text` whose numbers appear nowhere in what the family said."""
    known = set(re.findall(r"\d+", source or ""))
    known |= {str(n) for w, n in _WORDS.items() if re.search(rf"\b{w}\b", source or "", re.I)}
    return [m.group(0) for m in _QUANTITY.finditer(text or "")
            if any(n not in known for n in re.findall(r"\d+", m.group(1)))]


def vet_panel(panel: PanelResult, facts: CaseFacts, ctx: DisasterContext, source: str | None) -> PanelResult:
    v = panel.final
    text = f"{v.causal_chain} {v.how_injury_occurred}"
    notes = [f"forbidden wording: {p.pattern if hasattr(p, 'pattern') else type(p).__name__}"[:80]
             for p, _ in _FORBIDDEN if p.search(text)]
    if source is not None:
        notes += [f"duration not in the account: {q}" for q in invented_quantities(text, source)]
    if not notes:
        return panel
    d = _disaster_phrase(facts, ctx)
    if panel.rules.label == v.label and panel.rules.causal_chain:
        chain, how = panel.rules.causal_chain, panel.rules.how_injury_occurred
    else:
        chain = f"{d} -> {v.mechanism.value.replace('_', ' ')} -> death." if v.mechanism else v.causal_chain
        how = INJURY_PHRASES[v.mechanism].format(d=d) if v.mechanism in INJURY_PHRASES else ""
    final = v.model_copy(update={"causal_chain": chain, "how_injury_occurred": how})
    return panel.model_copy(update={"final": final, "vetted": notes})

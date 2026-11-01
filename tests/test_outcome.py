"""The vetted outcome messages: every label, every mechanism, both languages, none of the forbidden wording."""

import pytest

from counted.outcome import looks_spanish, message
from counted.policy.guards import _FORBIDDEN
from counted.schemas import CaseFacts, DisasterContext, Label, Mechanism, PanelResult, Verdict

CTX = DisasterContext(declared=True, declaration="DR-4586-TX", declaration_title="Severe Winter Storms", individual_assistance=True)


def panel(label, mechanism=None):
    v = Verdict(label=label, mechanism=mechanism, causal_chain="x", confidence=0.9)
    return PanelResult(final=v, rules=v, unanimous=True, adjudicated=False, context=CTX)


CASES = [(Label.DIRECT, m) for m in Mechanism] + [(Label.INDIRECT, m) for m in Mechanism] +         [(Label.NOT_RELATED, None), (Label.POSSIBLE, None), (Label.INDIRECT, None)]


@pytest.mark.parametrize("language", ["en", "es"])
@pytest.mark.parametrize("label,mechanism", CASES)
def test_outcome_messages_are_clean(label, mechanism, language):
    facts = CaseFacts(language=language, county="Harris", disaster_name="Winter Storm Uri")
    text = message(facts, CTX, panel(label, mechanism))
    assert not any(p.search(text) for p, _ in _FORBIDDEN), text
    assert ("borrador" in text or "no encontró" in text) if language == "es" else ("draft" in text or "did not find" in text)


def test_spanish_is_detected_from_what_the_family_writes():
    assert looks_spanish("Mi mamá murió después del huracán, se fue la luz en la casa")
    assert not looks_spanish("My mother died after the hurricane when the power went out")

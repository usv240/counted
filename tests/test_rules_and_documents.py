"""The deterministic half of Counted: the CDC decision tree and the documents it drafts. No network, no model."""

import re
from datetime import date

import pytest

from counted.documents import build_documents
from counted.policy.guards import _FORBIDDEN, redact
from counted.rules import classify
from counted.schemas import (DIRECT_MECHANISMS, CaseFacts, DisasterContext, DisasterType, Evidence, Label, Mechanism,
                             PanelResult)

URI = DisasterContext(declared=True, declaration="DR-4586-TX", declaration_title="Severe Winter Storms",
                      incident_begin=date(2021, 2, 11), incident_end=date(2021, 2, 21), individual_assistance=True,
                      within_incident_window=True)


def facts(*evidence, disaster=DisasterType.WINTER_STORM, **kw) -> CaseFacts:
    return CaseFacts(disaster_type=disaster, disaster_name="Winter Storm Uri",
                     evidence=[Evidence(mechanism=m, detail=d, quote=q) for m, d, q in evidence], **kw)


OXYGEN = (Mechanism.POWER_DEPENDENT_DEVICE, "Home oxygen concentrator stopped when the power failed",
          "her oxygen machine stopped when the lights went out")


def test_power_dependent_device_is_indirect():
    v = classify(facts(OXYGEN), URI)
    assert v.label == Label.INDIRECT and v.mechanism == Mechanism.POWER_DEPENDENT_DEVICE
    assert "Winter Storm Uri" in v.causal_chain


def test_hypothermia_is_direct_only_when_cold_is_the_disaster():
    cold = (Mechanism.ENVIRONMENTAL_TEMPERATURE, "House fell to 38 degrees for three days", "it was freezing inside")
    assert classify(facts(cold), URI).label == Label.DIRECT
    assert classify(facts(cold, disaster=DisasterType.HURRICANE), URI).label == Label.INDIRECT


def test_drowning_in_a_winter_storm_is_indirect():
    # CDC and Texas DSHS: a drowning after a crash on ice is not the storm's own water.
    drown = (Mechanism.DROWNING, "Car slid off an icy road into a pond", "his truck went into the pond")
    assert classify(facts(drown), URI).label == Label.INDIRECT
    assert classify(facts(drown, disaster=DisasterType.HURRICANE), URI).label == Label.DIRECT


def test_stress_alone_does_not_commit():
    stress = (Mechanism.STRESS_CARDIAC, "Heart attack during the storm", "he was so stressed")
    v = classify(facts(stress), URI)
    assert v.label == Label.POSSIBLE and v.missing


def test_unrelated_death_is_not_related_even_under_pressure():
    v = classify(facts(unrelated_explanation="hospice for terminal cancer since August"), URI)
    assert v.label == Label.NOT_RELATED


def test_manner_concern_goes_to_a_human():
    v = classify(facts(OXYGEN, manner_concern="suicide"), URI)
    assert v.label == Label.POSSIBLE and "certifier" in v.causal_chain


def test_death_long_after_the_storm_is_not_related():
    late = URI.model_copy(update={"within_incident_window": False, "days_after_incident_end": 120})
    assert classify(facts(OXYGEN), late).label == Label.NOT_RELATED


def test_every_direct_mechanism_is_direct_in_its_own_disaster():
    for m in DIRECT_MECHANISMS:
        disaster = DisasterType.WINTER_STORM if m == Mechanism.ENVIRONMENTAL_TEMPERATURE else DisasterType.HURRICANE
        assert classify(facts((m, "detail", "quote"), disaster=disaster), URI).label == Label.DIRECT, m


@pytest.mark.parametrize("language", ["en", "es"])
@pytest.mark.parametrize("mechanism", list(Mechanism))
def test_documents_never_use_wording_the_guards_forbid(mechanism, language):
    f = facts((mechanism, "Something the storm caused", "what the family said"), language=language,
              decedent_age=81, date_of_death=date(2021, 2, 17), county="Travis", state="TX")
    verdict = classify(f, URI)
    panel = PanelResult(final=verdict, rules=verdict, unanimous=True, adjudicated=False, context=URI)
    docs = build_documents(f, URI, panel)
    text = "\n".join(v if isinstance(v, str) else str(v) for v in docs.values())
    text = re.sub(r'"[^"\n]{0,80}"', "", text)  # a phrase named in quotes ("FEMA rejects '...'") is advice, not usage
    for pattern, _ in _FORBIDDEN:
        assert not pattern.search(text), f"{pattern.pattern} found in documents for {mechanism}/{language}"


def test_natural_manner_indirect_death_names_the_disaster_in_part_ii():
    f = facts(OXYGEN, date_of_death=date(2021, 2, 17))
    v = classify(f, URI)
    panel = PanelResult(final=v, rules=v, unanimous=True, adjudicated=False, context=URI)
    statement = build_documents(f, URI, panel)["certifier_statement"]
    assert "Part II, other significant conditions** (use if the manner of death is natural): Loss of electric power " \
           "to a medical device during Winter Storm Uri (February 2021)" in statement


def test_injury_death_has_no_part_ii_line():
    co = (Mechanism.CARBON_MONOXIDE, "Generator running in the garage", "the generator was in the garage")
    f = facts(co)
    v = classify(f, URI)
    panel = PanelResult(final=v, rules=v, unanimous=True, adjudicated=False, context=URI)
    assert v.label == Label.INDIRECT
    assert "(use if the manner of death is natural): n/a" in build_documents(f, URI, panel)["certifier_statement"]


def test_redaction():
    out = redact("SSN 123-45-6789, call (512) 555-0199 or +1 512.555.0199, mail ana.r@example.org")
    assert "6789" not in out and "0199" not in out and "@" not in out
    assert out.count("[phone removed]") == 2

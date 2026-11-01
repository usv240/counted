"""A family can stop and come back later: the conversation is restored from memory, and the case file is rebuilt
from the tool calls in it, so nothing the family said has to be asked again."""

from counted.agents import interviewer
from counted.agents.interviewer import CaseSession, build_interviewer, rebuild_case
from counted.schemas import DisasterContext

from scripted import ScriptedModel

URI = DisasterContext(declared=True, declaration="DR-4586-TX", individual_assistance=True, within_incident_window=True)
SAID = "My mom used home oxygen and the oxygen machine stopped when the power went out during the freeze."


def test_case_file_survives_a_restart(monkeypatch):
    monkeypatch.setattr(interviewer, "geocode", lambda a: {"county": "Harris", "state": "TX", "source": "test"})
    monkeypatch.setattr(interviewer, "disaster_context", lambda *a, **k: URI.model_copy(deep=True))
    script = [
        [{"tool": "record_details", "input": {"relationship": "daughter", "address": "Houston, TX",
                                               "date_of_death": "2021-02-17", "disaster_type": "winter_storm"}},
         {"tool": "record_circumstance", "input": {"mechanism": "power_dependent_medical_device",
                                                    "detail": "Oxygen stopped in the outage",
                                                    "quote": "the oxygen machine stopped when the power went out"}},
         {"tool": "record_circumstance", "input": {"mechanism": "loss_of_utilities", "detail": "invented",
                                                    "quote": "the storm killed her"}},  # blocked by the quote guard
         {"tool": "check_disaster_context", "input": {}}],
        "Thank you. Is there anything else you remember?",
    ]
    before = CaseSession()
    agent = build_interviewer(model=ScriptedModel(script))
    agent(SAID, invocation_state={"session": before, "role": "family", "consent": None})

    after = rebuild_case(CaseSession(id=before.id), agent.messages)  # a new process, same restored conversation
    assert [e.quote for e in after.facts.evidence] == ["the oxygen machine stopped when the power went out"]
    assert after.facts.evidence == before.facts.evidence
    assert (after.facts.relationship, after.facts.county, str(after.facts.date_of_death)) == ("daughter", "Harris", "2021-02-17")
    assert after.context_checked and after.context.declaration == "DR-4586-TX"

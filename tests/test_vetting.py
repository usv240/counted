"""Model-written lines are checked before they reach a document a certifier may sign."""

from counted.rules import classify
from counted.schemas import CaseFacts, DisasterContext, DisasterType, Evidence, Mechanism, PanelResult, Verdict
from counted.vetting import invented_quantities, vet_panel

CTX = DisasterContext(declared=True, declaration="DR-4586-TX", declaration_title="Severe Winter Storms")
ACCOUNT = ("The power went out on February 15 and did not come back for two days. Her oxygen machine stopped and the "
           "backup tank ran out the next morning. She died at home on 2021-02-17.")
FACTS = CaseFacts(disaster_type=DisasterType.WINTER_STORM, disaster_name="Winter Storm Uri", evidence=[
    Evidence(mechanism=Mechanism.POWER_DEPENDENT_DEVICE, detail="Oxygen concentrator stopped in the outage",
             quote="Her oxygen machine stopped")])


def panel_with(how: str, chain: str = "Winter Storm Uri caused an outage that stopped her oxygen concentrator.") -> PanelResult:
    rules = classify(FACTS, CTX)
    final = rules.model_copy(update={"how_injury_occurred": how, "causal_chain": chain})
    return PanelResult(final=final, rules=rules, unanimous=True, adjudicated=False, context=CTX)


def test_an_invented_duration_falls_back_to_the_rules_wording():
    # The showcase run wrote this from an account that gave only dates.
    p = vet_panel(panel_with("Without supplemental oxygen for approximately 36-48 hours prior to death."), FACTS, CTX, ACCOUNT)
    assert "36" not in p.final.how_injury_occurred and p.vetted
    assert p.final.how_injury_occurred == p.rules.how_injury_occurred


def test_durations_the_family_gave_are_kept():
    how = "Power outage of 2 days stopped her oxygen concentrator."  # "two days" is in the account
    assert vet_panel(panel_with(how), FACTS, CTX, ACCOUNT).final.how_injury_occurred == how


def test_forbidden_wording_in_the_chain_is_replaced():
    p = vet_panel(panel_with("x", chain="The outage may have contributed to her death."), FACTS, CTX, ACCOUNT)
    assert "may have" not in p.final.causal_chain and p.vetted


def test_quantities():
    assert invented_quantities("for about 36 hours", "it lasted a day") == ["36 hours"]
    assert invented_quantities("over three days, 3 days", "three days without power") == []

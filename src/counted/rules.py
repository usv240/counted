"""The CDC decision tree, as code.

Mirrors the steps in the CDC/NCHS "Reference Guide for Certification of Deaths in the Event of a
Natural, Human-induced, or Chemical/Radiological Disaster" (2017):

  Step 1   Did a disaster occur, and does the death fall in its place and time?
  Step 2a  Was the death caused by the forces of the disaster or their direct consequences?  -> DIRECT
  Step 2b  Did unsafe or unhealthy conditions created by the disaster contribute?            -> INDIRECT

This engine never reads free text and never calls a model. It only sees structured evidence the
interview extracted, so it can be wrong only in ways a reviewer can see.
"""

from __future__ import annotations

from .config import AFTERMATH_WINDOW_DAYS
from .schemas import (
    DIRECT_MECHANISMS,
    CaseFacts,
    DisasterContext,
    DisasterType,
    Evidence,
    Label,
    Mechanism,
    Verdict,
)

# Temperature exposure is the disaster itself in a winter storm or heat wave (direct). In a hurricane
# it arrives through a power outage, which makes it indirect (CDC MMWR, Hurricane Irma, 2018).
TEMPERATURE_IS_THE_DISASTER = {DisasterType.WINTER_STORM, DisasterType.HEAT_WAVE}

# Rank indirect mechanisms so the most specific, most actionable one names the case.
INDIRECT_PRIORITY = [
    Mechanism.CARBON_MONOXIDE,
    Mechanism.POWER_DEPENDENT_DEVICE,
    Mechanism.INFECTION,
    Mechanism.HEALTHCARE_DISRUPTION,
    Mechanism.FIRE_ALTERNATIVE_HEAT,
    Mechanism.ELECTROCUTION,
    Mechanism.CLEANUP_OR_PREP_INJURY,
    Mechanism.EVACUATION,
    Mechanism.VEHICLE_CRASH,
    Mechanism.FALL,
    Mechanism.UTILITY_LOSS,
    Mechanism.ENVIRONMENTAL_TEMPERATURE,
    Mechanism.CHRONIC_EXACERBATION,
    Mechanism.STRESS_CARDIAC,
]

DIRECT_PRIORITY = [
    Mechanism.DROWNING,
    Mechanism.STRUCTURAL_COLLAPSE,
    Mechanism.STRUCK_BY_OBJECT,
    Mechanism.WIND_TRAUMA,
    Mechanism.WILDFIRE,
    Mechanism.ENVIRONMENTAL_TEMPERATURE,
]

# Stress alone is the category examiners disagree on most; on its own it is never enough to commit.
WEAK_ALONE = {Mechanism.STRESS_CARDIAC}

INJURY_PHRASES = {
    Mechanism.DROWNING: "Drowned in floodwater during {d}",
    Mechanism.STRUCK_BY_OBJECT: "Struck by falling tree or debris during {d}",
    Mechanism.STRUCTURAL_COLLAPSE: "Structure collapsed during {d}",
    Mechanism.WIND_TRAUMA: "Blunt force injuries from high winds during {d}",
    Mechanism.WILDFIRE: "Burns and smoke inhalation in wildfire ({d})",
    Mechanism.ENVIRONMENTAL_TEMPERATURE: "Exposure to extreme environmental temperature during {d}",
    Mechanism.UTILITY_LOSS: "Loss of electrical power and heating/cooling due to {d}",
    Mechanism.HEALTHCARE_DISRUPTION: "Unable to obtain medical care (e.g. dialysis) due to {d}",
    Mechanism.POWER_DEPENDENT_DEVICE: "Loss of electrical power to home medical equipment due to {d}",
    Mechanism.CARBON_MONOXIDE: "Carbon monoxide from generator or fuel-burning device used during power outage from {d}",
    Mechanism.CLEANUP_OR_PREP_INJURY: "Injured while preparing for or cleaning up after {d}",
    Mechanism.EVACUATION: "Died during evacuation from {d}",
    Mechanism.VEHICLE_CRASH: "Motor vehicle crash in hazardous conditions caused by {d}",
    Mechanism.FIRE_ALTERNATIVE_HEAT: "House fire from alternative heating or lighting during power outage from {d}",
    Mechanism.CHRONIC_EXACERBATION: "Chronic illness exacerbated by conditions created by {d}",
    Mechanism.STRESS_CARDIAC: "Cardiac event attributed to physical or emotional stress of {d}",
    Mechanism.FALL: "Fall in unsafe conditions created by {d}",
    Mechanism.ELECTROCUTION: "Electrocution from downed or damaged power lines after {d}",
    Mechanism.INFECTION: "Infection of a wound or exposure sustained in floodwater or debris during {d}",
}


def _first(evidence: list[Evidence], order: list[Mechanism]) -> Evidence | None:
    for mechanism in order:
        for item in evidence:
            if item.mechanism == mechanism:
                return item
    return None


def _disaster_phrase(facts: CaseFacts, ctx: DisasterContext) -> str:
    return facts.disaster_name or ctx.declaration_title or (facts.disaster_type or "the disaster").replace("_", " ")


def classify(facts: CaseFacts, ctx: DisasterContext | None = None) -> Verdict:
    """Run the CDC decision tree over structured facts. Deterministic and side-effect free."""
    ctx = ctx or DisasterContext()
    d = _disaster_phrase(facts, ctx)

    # Step 1: no disaster, or a death outside its window, is not a disaster death.
    if ctx.declared and ctx.within_incident_window is False:
        late = ctx.days_after_incident_end
        if late is not None and late > AFTERMATH_WINDOW_DAYS:
            return Verdict(
                label=Label.NOT_RELATED,
                causal_chain=f"Death occurred {late} days after {d} ended, beyond the {AFTERMATH_WINDOW_DAYS}-day aftermath window.",
                evidence_used=[f"Incident period ended {ctx.incident_end}"],
                confidence=0.85,
            )

    if facts.manner_concern in {"homicide", "suicide", "undetermined"}:
        return Verdict(
            label=Label.POSSIBLE,
            causal_chain=f"Manner of death raised as {facts.manner_concern}; attribution must be made by the certifier.",
            missing=["Medicolegal investigation of manner of death"],
            confidence=0.9,
        )

    evidence = list(facts.evidence)
    if not evidence:
        if facts.unrelated_explanation:
            return Verdict(
                label=Label.NOT_RELATED,
                causal_chain=f"No disaster-related circumstance described; {facts.unrelated_explanation}.",
                evidence_used=[facts.unrelated_explanation],
                confidence=0.8,
            )
        return Verdict(
            label=Label.POSSIBLE,
            causal_chain="No disaster-related circumstance has been established yet.",
            missing=["What changed at home during the disaster (power, water, heat, care, access)"],
            confidence=0.5,
        )

    # Temperature exposure is direct only when the temperature itself is the disaster.
    temperature_direct = facts.disaster_type in TEMPERATURE_IS_THE_DISASTER
    # Drowning is direct only when the disaster's own water did it (flood, surge, storm rain). In a winter storm or
    # heat wave a drowning comes through a crash on ice or a fall, which CDC and Texas DSHS class as indirect.
    water_is_the_disaster = facts.disaster_type not in TEMPERATURE_IS_THE_DISASTER
    direct_candidates = [
        e for e in evidence
        if e.mechanism in DIRECT_MECHANISMS
        and (e.mechanism != Mechanism.ENVIRONMENTAL_TEMPERATURE or temperature_direct)
        and (e.mechanism != Mechanism.DROWNING or water_is_the_disaster)
    ]

    # Step 2a: direct.
    hit = _first(direct_candidates, DIRECT_PRIORITY)
    if hit:
        return Verdict(
            label=Label.DIRECT,
            mechanism=hit.mechanism,
            causal_chain=f"{d} -> {hit.detail} -> death.",
            evidence_used=[x for x in (hit.quote, hit.detail) if x],
            confidence=0.9,
            how_injury_occurred=INJURY_PHRASES[hit.mechanism].format(d=d),
        )

    # Step 2b: indirect. Stress alone does not commit.
    indirect = [e for e in evidence if e not in direct_candidates]
    substantive = [e for e in indirect if e.mechanism not in WEAK_ALONE]
    if not substantive:
        only = indirect[0]
        return Verdict(
            label=Label.POSSIBLE,
            mechanism=only.mechanism,
            causal_chain=f"Only {only.mechanism.value.replace('_', ' ')} described; CDC guidance needs a concrete unsafe condition.",
            evidence_used=[x for x in (only.quote, only.detail) if x],
            missing=["A specific condition the disaster created (power loss, missed care, exposure, injury)"],
            confidence=0.55,
        )

    hit = _first(substantive, INDIRECT_PRIORITY) or substantive[0]
    contributing = [e.detail for e in substantive if e is not hit][:3]
    chain = f"{d} -> {hit.detail}"
    if contributing:
        chain += " (also: " + "; ".join(contributing) + ")"
    return Verdict(
        label=Label.INDIRECT,
        mechanism=hit.mechanism,
        causal_chain=chain + " -> death.",
        evidence_used=[x for e in substantive for x in (e.quote, e.detail) if x][:6],
        confidence=0.85 if facts.unrelated_explanation is None else 0.6,
        missing=["Certifier review of competing explanation: " + facts.unrelated_explanation] if facts.unrelated_explanation else [],
        how_injury_occurred=INJURY_PHRASES[hit.mechanism].format(d=d),
    )

"""Shared data models: what the interview captures, what the panel decides, what the case file holds."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class DisasterType(StrEnum):
    HURRICANE = "hurricane"
    WINTER_STORM = "winter_storm"
    HEAT_WAVE = "heat_wave"
    FLOOD = "flood"
    WILDFIRE = "wildfire"
    TORNADO = "tornado"
    OTHER = "other"


class Label(StrEnum):
    """The four outcomes. FEMA rejects 'may have been caused by', so there is no hedged middle label:
    `possible` means Counted declines to commit and refers the case to a human examiner."""

    DIRECT = "direct"
    INDIRECT = "indirect"
    NOT_RELATED = "not_related"
    POSSIBLE = "possible"


class Mechanism(StrEnum):
    """CDC disaster-death circumstance categories (CDC/NCHS Reference Guide, 2017; CDC MMWR taxonomies)."""

    # Direct: the physical forces of the disaster or their immediate consequences.
    DROWNING = "drowning_flood_surge"
    STRUCK_BY_OBJECT = "struck_by_debris_or_tree"
    STRUCTURAL_COLLAPSE = "structural_collapse"
    WIND_TRAUMA = "wind_or_tornado_trauma"
    WILDFIRE = "wildfire_burns_or_smoke"
    ENVIRONMENTAL_TEMPERATURE = "environmental_cold_or_heat_exposure"
    # Indirect: unsafe or unhealthy conditions before, during or after the disaster.
    UTILITY_LOSS = "loss_of_utilities"
    HEALTHCARE_DISRUPTION = "loss_of_health_care"
    POWER_DEPENDENT_DEVICE = "power_dependent_medical_device"
    CARBON_MONOXIDE = "carbon_monoxide"
    CLEANUP_OR_PREP_INJURY = "cleanup_or_preparation_injury"
    EVACUATION = "evacuation_or_fleeing"
    VEHICLE_CRASH = "motor_vehicle_crash"
    FIRE_ALTERNATIVE_HEAT = "fire_from_alternative_heat_or_light"
    CHRONIC_EXACERBATION = "exacerbation_of_chronic_illness"
    STRESS_CARDIAC = "stress_related_cardiac_event"
    FALL = "fall_in_unsafe_conditions"
    ELECTROCUTION = "electrocution"
    INFECTION = "infection_from_floodwater_or_disaster_injury"


DIRECT_MECHANISMS = {
    Mechanism.DROWNING,
    Mechanism.STRUCK_BY_OBJECT,
    Mechanism.STRUCTURAL_COLLAPSE,
    Mechanism.WIND_TRAUMA,
    Mechanism.WILDFIRE,
    Mechanism.ENVIRONMENTAL_TEMPERATURE,
}


class _Lenient(BaseModel):
    """Some models send null for an empty list or string. Accept it instead of looping on validation."""

    @model_validator(mode="before")
    @classmethod
    def _nulls_to_empty(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for name, f in cls.model_fields.items():
                if data.get(name, ...) is None and f.default_factory is list:
                    data[name] = []
                elif data.get(name, ...) is None and f.default == "":
                    data[name] = ""
        return data


class Evidence(BaseModel):
    """One circumstance the family described, kept with their own words so every verdict is traceable."""

    mechanism: Mechanism
    detail: str = Field(description="What happened, in plain words (e.g. 'oxygen concentrator stopped when power went out').")
    quote: str = Field(default="", description="The relative's own words that support this, verbatim.")
    hours_before_death: float | None = Field(default=None, description="How long before the death this began, if known.")


class CaseFacts(_Lenient):
    """Everything the interview establishes. Filled incrementally; nothing here is guessed."""

    case_id: str = ""
    language: str = "en"
    relationship: str = Field(default="", description="Relationship of the person interviewed to the decedent.")
    decedent_age: int | None = None
    decedent_sex: str | None = None
    date_of_death: date | None = None
    address: str | None = None
    county: str | None = None
    state: str | None = None
    county_fips: str | None = None
    lat: float | None = None
    lon: float | None = None
    disaster_name: str | None = None
    disaster_type: DisasterType | None = None
    place_of_death: str | None = Field(default=None, description="home, vehicle, outdoors, hospital, shelter...")
    certificate_cause: str | None = Field(default=None, description="Cause written on the death certificate, if the family knows it.")
    chronic_conditions: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    manner_concern: str | None = Field(default=None, description="'homicide', 'suicide' or 'undetermined' if raised. Routed to a human.")
    unrelated_explanation: str | None = Field(default=None, description="Anything suggesting the death would have happened anyway.")
    narrative: str = Field(default="", description="The relative's account in their own words, condensed.")


class DisasterContext(BaseModel):
    """Facts Counted checks itself instead of trusting anyone's memory."""

    declared: bool = False
    declaration: str | None = None
    declaration_title: str | None = None
    incident_type: str | None = None
    incident_begin: date | None = None
    incident_end: date | None = None
    individual_assistance: bool = False
    within_incident_window: bool | None = None
    days_after_incident_end: int | None = None
    nws_warnings: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class Verdict(_Lenient):
    """One examiner's determination."""

    label: Label
    mechanism: Mechanism | None = None
    causal_chain: str = Field(description="Disaster -> condition -> death, in one or two sentences, CDC wording.")
    evidence_used: list[str] = Field(default_factory=list, description="Exact family quotes or checked facts relied on.")
    missing: list[str] = Field(default_factory=list, description="What would change or firm up this determination.")
    confidence: float = Field(ge=0, le=1)
    how_injury_occurred: str = Field(default="", description="Draft 'How injury occurred' line for the certificate, or empty.")


class PanelResult(BaseModel):
    final: Verdict
    rules: Verdict
    examiner: Verdict | None = None
    second_examiner: Verdict | None = None
    adjudicator: Verdict | None = None
    unanimous: bool
    adjudicated: bool
    context: DisasterContext

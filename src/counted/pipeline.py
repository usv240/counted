"""One-call assessment: an account of a death in, a determination and documents out.

Used by the public API (/v1/assess), the MCP server, the AgentCore entrypoint and the evaluation harness.
The live interview reaches the same panel through the interviewer's request_determination tool.
"""

from __future__ import annotations

import time
import uuid
from datetime import date

from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.models.routing import ModelRouter

from . import budget
from .agents.panel import run_panel
from .config import EXAMINER_MODEL, FALLBACK_MODEL, INTERVIEW_MODEL, REGION
from .documents import build_documents
from .policy.guards import redact
from .schemas import CaseFacts, DisasterContext, PanelResult
from .tools.facts import disaster_context, geocode
from .vetting import vet_panel

EXTRACT_PROMPT = """Extract structured case facts from an account of a death around a disaster.
Record ONLY what the account states. For each disaster-related circumstance, add an evidence item with the closest
mechanism id and a verbatim quote from the account. Do not infer circumstances that are not described.
If the account suggests homicide/suicide, set manner_concern. If it suggests the death would have happened anyway
(e.g. hospice, death before the disaster), set unrelated_explanation. Dates as YYYY-MM-DD."""


def extract_facts(account: str, language: str = "en") -> CaseFacts:
    model = ModelRouter([
        BedrockModel(model_id=INTERVIEW_MODEL, region_name=REGION, temperature=0),
        BedrockModel(model_id=FALLBACK_MODEL, region_name=REGION, temperature=0),
    ])
    agent = Agent(name="extractor", model=model, system_prompt=EXTRACT_PROMPT, callback_handler=None,
                  structured_output_model=CaseFacts)
    facts: CaseFacts = agent(redact(account)).structured_output
    facts.language = language
    return facts


def assess(account: str | None = None, facts: CaseFacts | None = None, *, language: str = "en",
           context: DisasterContext | None = None, check_public_records: bool = True) -> dict:
    """Full pipeline. Pass `facts` to skip extraction, `context` to skip public-record lookups."""
    budget.spend()
    t0 = time.perf_counter()
    if facts is None:
        facts = extract_facts(account or "", language)
    facts.case_id = facts.case_id or uuid.uuid4().hex[:12]
    if context is None:
        context = DisasterContext()
        if check_public_records and facts.address and facts.date_of_death:
            place = geocode(facts.address)
            if place:
                facts.county, facts.state = place.get("county"), place.get("state")
                facts.county_fips, facts.lat, facts.lon = place.get("county_fips"), place.get("lat"), place.get("lon")
            context = disaster_context(facts.state, facts.county, facts.date_of_death, facts.lat, facts.lon)
            if place:
                context.sources.insert(0, place["source"])
    panel: PanelResult = vet_panel(run_panel(facts, context), facts, context, account)
    return {
        "case_id": facts.case_id,
        "facts": facts.model_dump(mode="json"),
        "context": context.model_dump(mode="json"),
        "panel": panel.model_dump(mode="json"),
        "documents": build_documents(facts, context, panel),
        "elapsed_seconds": round(time.perf_counter() - t0, 1),
        "generated": date.today().isoformat(),
    }

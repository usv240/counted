"""Counted as an MCP server: any agent (a 211 helpline bot, a disaster case-management assistant, a medical
examiner's own tooling, Claude Desktop) can call Counted's tools.

Mounted at /mcp on the main service, or run standalone:  uv run counted-mcp
"""

from __future__ import annotations

import json
from datetime import date

from mcp.server.mcpserver import MCPServer

from ..pipeline import assess
from ..rules import classify
from ..schemas import CaseFacts, DisasterContext, Mechanism
from ..tools.facts import disaster_context, geocode

mcp = MCPServer(
    name="counted",
    title="Counted: disaster death attribution",
    description="Finds the disaster hidden inside a death, following CDC certification guidance, and drafts the "
                "certifier statement and FEMA Funeral Assistance packet. Drafts only; a human certifier signs.",
    website_url="https://github.com/usv240/counted",
)


@mcp.tool()
def assess_disaster_death(account: str, language: str = "en") -> dict:
    """Assess whether a death was directly, indirectly or not caused by a declared disaster.

    Args:
        account: What happened, in the family's or caseworker's words (age, place, date, disaster, circumstances).
        language: 'en' or 'es' for the family-facing documents.
    """
    r = assess(account, language=language)
    p = r["panel"]
    return {
        "case_id": r["case_id"],
        "determination": p["final"]["label"],
        "mechanism": p["final"].get("mechanism"),
        "causal_chain": p["final"]["causal_chain"],
        "how_injury_occurred": p["final"].get("how_injury_occurred"),
        "panel": {k: (p.get(k) or {}).get("label") for k in ("rules", "examiner", "second_examiner", "adjudicator")},
        "fema_declaration": r["context"].get("declaration"),
        "individual_assistance": r["context"].get("individual_assistance"),
        "certifier_statement_markdown": r["documents"]["certifier_statement"],
        "family_packet_markdown": r["documents"]["family_packet"],
    }


@mcp.tool()
def check_disaster_record(address: str, date_of_death: str) -> dict:
    """Check public records for a place and date: FEMA declaration, whether Individual Assistance (which pays
    funeral assistance) was approved, the incident period, and National Weather Service warnings in force.

    Args:
        address: Street address, or 'County, ST', or 'City, ST'.
        date_of_death: YYYY-MM-DD.
    """
    place = geocode(address) or {}
    ctx = disaster_context(place.get("state"), place.get("county"), date.fromisoformat(date_of_death),
                           place.get("lat"), place.get("lon"))
    return {"place": place, **ctx.model_dump(mode="json")}


@mcp.tool()
def cdc_decision_tree(facts_json: str, context_json: str = "{}") -> dict:
    """Run only the deterministic CDC decision tree (no model) over structured CaseFacts JSON.

    Args:
        facts_json: CaseFacts as JSON (see the resource counted://schema/case-facts).
        context_json: Optional DisasterContext as JSON.
    """
    v = classify(CaseFacts.model_validate_json(facts_json), DisasterContext.model_validate_json(context_json or "{}"))
    return v.model_dump(mode="json")


@mcp.resource("counted://schema/case-facts")
def case_facts_schema() -> str:
    """JSON schema of the facts Counted extracts from an interview."""
    return json.dumps(CaseFacts.model_json_schema(), indent=1)


@mcp.resource("counted://cdc/categories")
def cdc_categories() -> str:
    """The CDC circumstance categories Counted classifies into."""
    return json.dumps([m.value for m in Mechanism])


@mcp.prompt()
def family_interview() -> str:
    """Start a trauma-informed interview with a bereaved relative."""
    from ..agents.interviewer import SYSTEM_PROMPT
    return SYSTEM_PROMPT


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

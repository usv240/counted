"""The examiner panel, modelled on how disaster deaths are actually reviewed: independent opinions,
then adjudication only when they disagree.

  seat 1  CDC decision tree      deterministic code (rules.py): cannot hallucinate, cannot be persuaded
  seat 2  Claude examiner        reads the whole account like a medical examiner
  seat 3  Nova examiner          a second model family, so one model's blind spot is not the verdict
  chair   Adjudicator            runs ONLY if the three seats disagree (Strands Graph conditional edge)
"""

from __future__ import annotations

import json
import logging

from botocore.config import Config as BotocoreConfig
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.models.routing import ModelRouter
from strands.multiagent import GraphBuilder

from ..config import ADJUDICATOR_MODEL, EXAMINER_MODEL, FALLBACK_MODEL, REGION, SECOND_EXAMINER_MODEL
from ..rules import classify
from ..schemas import CaseFacts, DisasterContext, Label, PanelResult, Verdict

log = logging.getLogger(__name__)

CDC_BRIEF = """You are a medical examiner applying the CDC/NCHS "Reference Guide for Certification of Deaths in the
Event of a Natural, Human-induced, or Chemical/Radiological Disaster" (2017).

Labels:
- direct: death caused by the physical forces of the disaster or their direct consequences (drowning in flood or surge,
  struck by debris/tree, structural collapse, wind trauma, wildfire burns/smoke, or exposure to the extreme cold/heat
  when that temperature IS the disaster, e.g. hypothermia in a winter storm).
- indirect: unsafe or unhealthy conditions before, during or after the disaster contributed: loss of utilities
  (power, water, heat/cooling), loss of health care (missed dialysis, no oxygen, no medicines), power-dependent
  medical devices failing, carbon monoxide from generators, cleanup/preparation injuries, evacuation, crashes in
  hazardous conditions, fires from candles/alternative heat, exacerbation of chronic illness by those conditions,
  stress-related cardiac events WITH a concrete disaster stressor.
- not_related: no credible pathway from the disaster to the death, or the death falls outside its place/time.
- possible: you cannot commit (manner of death in question, or the evidence is too thin). FEMA rejects
  "may have been caused by", so use `possible` instead of hedging inside direct/indirect.

Two definitions that decide many cases (CDC 2017 guide; Texas DSHS applied them to every Winter Storm Uri death):
- Hypothermia or frostbite in a winter storm, and heat stroke in a heat wave, are DIRECT, even when a power outage
  left the home unheated or uncooled: the extreme temperature IS the disaster. (In a hurricane, heat illness from a
  lost air conditioner is indirect, because the hurricane is not a temperature event.)
- Drowning is direct only when the disaster's own water caused it (flood, storm surge). A car sliding on ice into a
  pond, or a fall into water during a winter storm, is indirect (a crash or fall in hazardous conditions).

Rules: rely only on the facts given. Cite the family's exact words in evidence_used. Never invent circumstances.
A death certificate cause like "cardiac arrest" does not rule out an indirect disaster pathway. Write
how_injury_occurred as one certificate-style line when label is direct or indirect, else empty."""


# A model call that stalls must fail fast so the router can switch to the backup model.
_BOTO = BotocoreConfig(connect_timeout=10, read_timeout=75, retries={"max_attempts": 2, "mode": "adaptive"})


def bedrock(model_id: str, temperature: float = 0, max_tokens: int = 1600) -> BedrockModel:
    return BedrockModel(model_id=model_id, region_name=REGION, temperature=temperature, max_tokens=max_tokens,
                        boto_client_config=_BOTO)


def _model(model_id: str, backup: str | None = None):
    primary = bedrock(model_id)
    if not backup:
        return primary
    return ModelRouter([primary, bedrock(backup)])


def _case_brief(facts: CaseFacts, ctx: DisasterContext) -> str:
    return (
        "CASE FACTS (from the family interview):\n"
        + facts.model_dump_json(indent=1, exclude={"lat", "lon", "case_id", "address"})
        + "\n\nPUBLIC-RECORD CHECKS (FEMA declaration, NWS warnings):\n"
        + ctx.model_dump_json(indent=1)
        + "\n\nGive your determination."
    )


def _verdict(state, node_id: str) -> Verdict | None:
    node = state.results.get(node_id)
    if not node or not node.result:
        return None
    return getattr(node.result, "structured_output", None)


def _ask(agent: Agent, brief: str) -> Verdict | None:
    try:
        agent.messages.clear()
        return agent(brief, limits={"structured_output_attempts": 3, "turns": 4}).structured_output
    except Exception as exc:
        log.warning("seat %s unavailable: %s", agent.name, exc)
        return None


def run_panel(facts: CaseFacts, ctx: DisasterContext) -> PanelResult:
    rules = classify(facts, ctx)

    examiner = Agent(name="examiner", model=_model(EXAMINER_MODEL, FALLBACK_MODEL), system_prompt=CDC_BRIEF,
                     structured_output_model=Verdict, callback_handler=None)
    second = Agent(name="second_examiner", model=_model(SECOND_EXAMINER_MODEL, FALLBACK_MODEL), system_prompt=CDC_BRIEF,
                   structured_output_model=Verdict, callback_handler=None)
    adjudicator = Agent(
        name="adjudicator",
        model=_model(ADJUDICATOR_MODEL, EXAMINER_MODEL),
        system_prompt=CDC_BRIEF + "\n\nYou are the adjudicating examiner. The panel disagreed. The deterministic CDC "
        "decision tree concluded:\n" + rules.model_dump_json(indent=1) + "\nWeigh all opinions against the facts and "
        "the CDC definitions, explain the deciding fact in causal_chain, and give the final determination.",
        structured_output_model=Verdict,
        callback_handler=None,
    )

    def disagreement(state) -> bool:
        a, b = _verdict(state, "examiner"), _verdict(state, "second_examiner")
        if a is None or b is None:
            return False
        return len({rules.label, a.label, b.label}) > 1

    builder = GraphBuilder()
    builder.add_node(examiner, "examiner")
    builder.add_node(second, "second_examiner")
    builder.add_node(adjudicator, "adjudicator")
    builder.set_entry_point("examiner")
    builder.set_entry_point("second_examiner")
    builder.add_edge("examiner", "adjudicator", condition=disagreement)
    builder.add_edge("second_examiner", "adjudicator", condition=disagreement)
    builder.set_node_timeout(150)
    builder.set_execution_timeout(320)
    graph = builder.build()

    brief = _case_brief(facts, ctx)
    try:
        result = graph(brief)
        a, b = _verdict(result, "examiner"), _verdict(result, "second_examiner")
        adj = _verdict(result, "adjudicator")
    except Exception as exc:
        # A seat that times out must not sink the case: re-seat the panel one examiner at a time,
        # each capped, and let whoever answers be heard.
        log.warning("panel graph failed (%s); re-seating examiners individually", exc)
        a, b, adj = _ask(examiner, brief), _ask(second, brief), None
        if len({v.label for v in (rules, a, b) if v}) > 1:
            adj = _ask(adjudicator, brief)
    seats = [v for v in (rules, a, b) if v is not None]
    unanimous = len({v.label for v in seats}) == 1

    if adj is not None:
        final = adj
    elif unanimous:
        # Prefer the examiner's prose, but the rules engine's mechanism when it named one.
        final = (a or rules).model_copy(update={"mechanism": rules.mechanism or (a.mechanism if a else None)})
    else:
        # Adjudicator unavailable: fall back to the most conservative opinion rather than guessing.
        final = rules if rules.label in (Label.POSSIBLE, Label.NOT_RELATED) else rules.model_copy(update={"label": Label.POSSIBLE})

    return PanelResult(final=final, rules=rules, examiner=a, second_examiner=b, adjudicator=adj,
                       unanimous=unanimous, adjudicated=adj is not None, context=ctx)


def panel_summary(p: PanelResult) -> str:
    seats = {"cdc_rules": p.rules, "claude": p.examiner, "nova": p.second_examiner, "adjudicator": p.adjudicator}
    return json.dumps({k: (v.label.value if v else None) for k, v in seats.items()})

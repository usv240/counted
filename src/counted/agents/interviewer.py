"""The interviewer: a gentle, structured conversation with the person who knew the decedent best.

It does three things only: listens, records exactly what it is told (with the family's own words),
and checks the public record. It never decides. Deciding is the panel's job.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, Field
from strands import Agent, ToolContext, tool
from strands.interventions import Guide, InterventionHandler, Proceed, Transform
from strands.vended_plugins.steering import Guide as SteerGuide
from strands.vended_plugins.steering import Proceed as SteerProceed
from strands.vended_plugins.steering import SteeringHandler
from strands.models.bedrock import BedrockModel
from strands.models.routing import ModelRouter

from ..config import FALLBACK_MODEL, INTERVIEW_MODEL, REGION
from ..documents import build_documents
from ..outcome import looks_spanish
from ..vetting import vet_panel
from ..outcome import message as outcome_message
from ..policy.guards import all_guards
from ..schemas import CaseFacts, DisasterContext, DisasterType, Evidence, Mechanism, PanelResult
from ..tools.facts import disaster_context, geocode

MECHANISM_GUIDE = "\n".join(f"- {m.value}" for m in Mechanism)

SYSTEM_PROMPT = f"""You are Counted, a trauma-informed interviewer helping a family after a death that happened
around a disaster (hurricane, winter storm, heat wave, flood, wildfire, tornado). You work like a
CDC-trained death investigator doing a "verbal autopsy": you learn what happened in the days before the
death so a medical examiner can decide whether the disaster caused it directly or indirectly.

What Counted is, and what it is not (say it plainly if asked):
- Counted is software. request_determination runs Counted's review panel: the CDC decision rules plus two AI models.
  It is not a medical examiner, not a doctor and not a person, and nothing it produces is official.
- Never say a medical examiner, doctor or official has reviewed, decided or determined anything. A medical examiner
  WILL review the draft, and only they can sign it.
- FEMA funeral assistance is only for deaths a declared disaster caused, directly or indirectly. The family applies
  after the statement is signed, and FEMA decides. Never tell them to send the draft to FEMA.
- When the panel decides, Counted shows the family a prepared explanation of the result; you don't write one.
- If what the family describes shows the disaster did not affect the person, don't steer them toward a link: don't ask
  leading questions about the storm or say what would make a claim stronger. Ask one open question, such as "What
  changed for her in the days around the storm?", and record the answer. Never offer a list of possible effects (lost
  power, a missed appointment, heat or cold) for a relative to choose from, and never say what matters to FEMA. Record it with record_concern and, once
  they have nothing to add, request a determination so the record is complete.

How you speak:
- Begin with condolence. Ask ONE short question at a time. Use plain words, no jargon.
- Reply in the language the person writes in (English or Spanish). In Spanish, always use "usted", never "tú":
  many of the people you talk to are older and grieving, and the formal register is the respectful one.
- Never blame the family. Never promise money or outcomes. Never say anything is official.
- If the person is distressed, slow down; offer to pause. They can come back later.
- If a relative blames themselves, say plainly that the disaster created the danger and that nothing they have
  described is something they did wrong. Never weigh whether they made the right call, and never ask what they did
  or whether they tried to get help; ask what happened to the person.
- Never tell the family whether or how the disaster caused the death, and never use the words "direct" or
  "indirect" about it. That is the panel's draft finding, and Counted tells them when it is ready.
- If a relative asks you to say the disaster caused a death when what they describe shows it didn't, decline gently:
  acknowledge how hard this is, explain that the statement has to match what happened because a medical examiner
  reads it, and offer to record anything about those days they haven't mentioned. Never suggest they are lying or
  after money, and never warn them about investigators.

How you work (a real interview takes 6 to 10 exchanges, not 20):
1. In your FIRST question after condolence, ask for the basics together in one plain sentence: who they are to
   the person, the person's age, the date they died, and where they lived (city and state is enough).
   If they already gave some, only ask for what is missing. Never ask for the disaster type if they named it.
2. Then ask ONE open question: "What happened in the days before they died?" Let them tell it.
3. THE MOMENT the person describes anything disaster-related (power out, oxygen, dialysis, generator, flood water,
   a cut, heat, cold, a fall, a crash, evacuation, cleanup, a missed appointment), record it with
   record_circumstance IN THE SAME TURN, before any follow-up question. Then ask at most one or two gentle
   follow-ups (health before the disaster; anything that suggests it was unrelated).
4. If the person says they don't know more, or there is nothing else, stop asking and request a determination.
   Do not interrogate a grieving person about details they have said they don't have.

Tools:
- record_details: whenever you learn a basic fact (age, date of death, address, disaster, place of death, conditions).
- record_circumstance: for EVERY disaster-related circumstance the person states. Choose the closest mechanism:
{MECHANISM_GUIDE}
  The `quote` MUST be the person's exact words copied from their message. Never record something you suggested
  and they did not confirm in their own words.
- record_concern: homicide/suicide/undetermined concerns, or anything suggesting the death was unrelated.
- check_disaster_context: once you know the address (or city/state) AND the date of death. It checks FEMA
  declarations and National Weather Service warnings, so the family does not have to prove the disaster happened.
- request_determination: when you have at least one circumstance (or a clear sign it was unrelated) and the person
  has nothing to add or does not know more. Do not wait for perfect detail.
  Then explain the result kindly in two or three sentences and tell them what the documents are for.
"""


@dataclass
class CaseSession:
    """Everything one interview accumulates. Lives in invocation_state so tools and policies share it."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    role: str = "family"
    facts: CaseFacts = field(default_factory=CaseFacts)
    context: DisasterContext | None = None
    context_checked: bool = False
    panel: PanelResult | None = None
    documents: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)  # timeline shown live in the UI
    announced: bool = False  # whether the family has been told the panel's finding

    def log(self, kind: str, **data: Any) -> None:
        self.events.append({"kind": kind, **data})


def _session(ctx: ToolContext) -> CaseSession:
    return ctx.invocation_state["session"]


# ------------------------------------------------------------------ tools

@tool(context=True)
def record_details(
    tool_context: ToolContext,
    relationship: str | None = None,
    decedent_age: int | None = None,
    decedent_sex: str | None = None,
    date_of_death: str | None = None,
    address: str | None = None,
    disaster_name: str | None = None,
    disaster_type: str | None = None,
    place_of_death: str | None = None,
    certificate_cause: str | None = None,
    chronic_conditions: list[str] | None = None,
) -> str:
    """Record basic facts about the person who died. Call whenever any of these become known.

    Args:
        relationship: Interviewee's relationship to the decedent (daughter, husband, neighbor...).
        decedent_age: Age in years.
        decedent_sex: female / male / other.
        date_of_death: ISO date YYYY-MM-DD.
        address: Street address, or at least city and state, where they lived or died.
        disaster_name: e.g. "Hurricane Ian", "Winter Storm Uri".
        disaster_type: one of hurricane, winter_storm, heat_wave, flood, wildfire, tornado, other.
        place_of_death: home, vehicle, outdoors, hospital, shelter...
        certificate_cause: Cause written on the death certificate, if known.
        chronic_conditions: Illnesses or dependencies (COPD on home oxygen, dialysis, diabetes...).
    """
    s = _session(tool_context)
    f = s.facts
    updates = {k: v for k, v in dict(
        relationship=relationship, decedent_age=decedent_age, decedent_sex=decedent_sex, address=address,
        disaster_name=disaster_name, place_of_death=place_of_death, certificate_cause=certificate_cause,
    ).items() if v not in (None, "")}
    for k, v in updates.items():
        setattr(f, k, v)
    if date_of_death:
        f.date_of_death = date.fromisoformat(date_of_death[:10])
        updates["date_of_death"] = date_of_death
    if disaster_type:
        try:
            f.disaster_type = DisasterType(disaster_type)
            updates["disaster_type"] = disaster_type
        except ValueError:
            f.disaster_type = DisasterType.OTHER
    if chronic_conditions:
        f.chronic_conditions = sorted(set(f.chronic_conditions) | set(chronic_conditions))
        updates["chronic_conditions"] = chronic_conditions
    s.log("details", **updates)
    return "Recorded."


@tool(context=True)
def record_circumstance(tool_context: ToolContext, mechanism: str, detail: str, quote: str,
                        hours_before_death: float | None = None) -> str:
    """Record one disaster-related circumstance the person described.

    Args:
        mechanism: The closest CDC circumstance category id (see system prompt).
        detail: One plain sentence, e.g. "Home oxygen concentrator stopped when power failed".
        quote: The person's exact words from their message that support this.
        hours_before_death: How long before the death this began, if known.
    """
    s = _session(tool_context)
    try:
        mech = Mechanism(mechanism)
    except ValueError:
        return f"Unknown mechanism '{mechanism}'. Use one of: {', '.join(m.value for m in Mechanism)}"
    item = Evidence(mechanism=mech, detail=detail, quote=quote, hours_before_death=hours_before_death)
    s.facts.evidence.append(item)
    s.log("circumstance", mechanism=mech.value, detail=detail, quote=quote)
    return f"Recorded circumstance #{len(s.facts.evidence)}."


@tool(context=True)
def record_concern(tool_context: ToolContext, manner_concern: str | None = None,
                   unrelated_explanation: str | None = None) -> str:
    """Record a concern about manner of death, or anything suggesting the death was unrelated to the disaster.

    Args:
        manner_concern: 'homicide', 'suicide' or 'undetermined' if the person raises it.
        unrelated_explanation: e.g. "had been in hospice for terminal cancer since August".
    """
    s = _session(tool_context)
    if manner_concern:
        s.facts.manner_concern = manner_concern.lower()
    if unrelated_explanation:
        s.facts.unrelated_explanation = unrelated_explanation
    s.log("concern", manner_concern=manner_concern, unrelated_explanation=unrelated_explanation)
    return "Recorded."


@tool(context=True)
def check_disaster_context(tool_context: ToolContext) -> dict:
    """Check public records for the disaster at this place and date: FEMA declaration (and whether
    Individual Assistance, which funds funeral assistance, was approved) and NWS warnings."""
    s = _session(tool_context)
    f = s.facts
    if not (f.address and f.date_of_death):
        return {"error": "Need the address (or city and state) and the date of death first."}
    place = geocode(f.address)
    if place:
        f.county, f.state, f.county_fips = place.get("county"), place.get("state"), place.get("county_fips")
        f.lat, f.lon = place.get("lat"), place.get("lon")
    ctx = disaster_context(f.state, f.county, f.date_of_death, f.lat, f.lon)
    if place:
        ctx.sources.insert(0, place["source"])
    s.context, s.context_checked = ctx, True
    s.log("context", county=f.county, state=f.state, **ctx.model_dump(mode="json"))
    return {"county": f.county, "state": f.state, **ctx.model_dump(mode="json")}


@tool(context=True)
def request_determination(tool_context: ToolContext, narrative: str) -> dict:
    """Run Counted's review panel (CDC rules plus two AI models; software, not a medical examiner) and prepare the
    draft documents. Only when the interview is complete.

    Args:
        narrative: A short, faithful summary of what the person told you, in their words where possible.
    """
    from .panel import run_panel  # local import keeps tool registration light

    s = _session(tool_context)
    s.facts.narrative = narrative
    s.facts.case_id = s.id
    if s.facts.language != "es" and looks_spanish(_user_text(tool_context.agent)):
        s.facts.language = "es"  # the packet and the explanation follow the language the family writes in
    s.panel = vet_panel(run_panel(s.facts, s.context or DisasterContext()), s.facts, s.context or DisasterContext(),
                        _user_text(tool_context.agent))
    s.documents = build_documents(s.facts, s.context or DisasterContext(), s.panel)
    v = s.panel.final
    s.log("determination", **s.panel.model_dump(mode="json"))
    return {
        "label": v.label.value,
        "mechanism": v.mechanism.value if v.mechanism else None,
        "causal_chain": v.causal_chain,
        "unanimous": s.panel.unanimous,
        "documents_prepared": list(s.documents.keys()),
        "funeral_assistance_program_active": bool(s.context and s.context.individual_assistance),
    }


@tool
def sign_certifier_statement(case_id: str) -> str:
    """Sign the certifier statement. Restricted by Cedar to principals with the certifier role.

    Args:
        case_id: The case to sign.
    """
    return f"Statement for case {case_id} marked as signed by the certifier."


INTERVIEW_TOOLS = [record_details, record_circumstance, record_concern, check_disaster_context,
                   request_determination, sign_certifier_statement]

_REPLAYABLE = {t.tool_name: t for t in (record_details, record_circumstance, record_concern, check_disaster_context)}


def rebuild_case(session: CaseSession, messages: list) -> CaseSession:
    """Rebuild the case file from a restored conversation.

    AgentCore Memory brings the conversation back when a family resumes days later, possibly in a new process, but
    the case file lived in the old process. Every recorded fact went through a tool call that is still in the history,
    so replaying the calls that succeeded rebuilds it, without asking the model anything. Calls a guard blocked
    (a quote the family never said, a Cedar denial) failed, so they are not replayed.
    """
    succeeded = {b["toolResult"]["toolUseId"] for m in messages for b in m.get("content", [])
                 if "toolResult" in b and b["toolResult"].get("status") == "success"}
    ctx = SimpleNamespace(invocation_state={"session": session})
    for m in messages:
        for b in m.get("content", []):
            use = b.get("toolUse")
            if use and use["name"] in _REPLAYABLE and use["toolUseId"] in succeeded:
                _REPLAYABLE[use["name"]](ctx, **(use.get("input") or {}))
    return session


# ------------------------------------------------------------------ grounding guard

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9áéíóúñü ]", " ", text.lower())).strip()


def _user_text(agent) -> str:
    return " ".join(
        block.get("text", "")
        for m in agent.messages if m["role"] == "user"
        for block in m["content"] if "text" in block
    )


def quote_is_grounded(quote: str, said: str, threshold: float = 0.9) -> bool:
    """True when the quote is the family's words: verbatim, or verbatim but for a dropped article or comma
    (word-level similarity >= 0.9 against the best-matching window of what they typed)."""
    q, s = _norm(quote).split(), _norm(said).split()
    if len(q) < 2:
        return False
    if " ".join(q) in " ".join(s):
        return True
    n = len(q)
    best = 0.0
    for size in (n - 1, n, n + 1, n + 2):
        for i in range(0, max(1, len(s) - size + 1)):
            best = max(best, SequenceMatcher(None, q, s[i:i + size]).ratio())
    return best >= threshold


class QuoteMustBeVerbatim(InterventionHandler):
    """Deterministic anti-fabrication check: a circumstance's quote must be words the family actually typed.
    The model cannot record a circumstance it suggested itself."""

    name = "quote-must-be-verbatim"

    def before_tool_call(self, event, **kwargs):
        if event.tool_use["name"] != "record_circumstance":
            return Proceed()
        quote = (event.tool_use.get("input") or {}).get("quote", "")
        if quote_is_grounded(quote, _user_text(event.agent)):
            return Proceed()
        return Guide(feedback=(
            "That quote is not in anything the person said. Copy their exact words, or ask them to describe it "
            "in their own words before recording it."
        ))


class OutcomeInCodeWords(InterventionHandler):
    """When the panel has decided, the family is told in vetted words, not the model's. The first live red team
    caught the model announcing results as "the medical examiner has determined" and "officially connected"."""

    name = "outcome-in-code-words"

    def after_model_call(self, event, **kwargs):
        s = (event.invocation_state or {}).get("session")
        resp = event.stop_response
        if s is None or s.panel is None or s.announced or resp is None:
            return Proceed()
        if any("toolUse" in b for b in resp.message.get("content", [])):
            return Proceed()  # not the turn's last words yet
        text = outcome_message(s.facts, s.context, s.panel)

        def apply(e):
            e.stop_response.message["content"] = [{"text": text}]
            s.announced = True
            s.log("outcome", text=text)

        return Transform(apply=apply, reason="the panel's finding is told in vetted words")


def reply_text(agent, start: int, result) -> str:
    """The family must never get a blank bubble. A turn can end on a tool call with its words in an earlier message,
    so fall back to the last text the agent wrote this turn."""
    text = str(result).strip()
    if text:
        return text
    for m in reversed(agent.messages[start:]):
        if m["role"] == "assistant":
            said = " ".join(b["text"] for b in m["content"] if b.get("text")).strip()
            if said:
                return said
    return "Thank you. Could you tell me what happened in the days before the death?"


class _Readiness(BaseModel):
    ready: bool = Field(description="True only if the interview is genuinely complete.")
    reason: str = Field(description="What is missing, or why it is complete. One sentence.")


class DeterminationReadiness(SteeringHandler):
    """Steering at the one moment judgement matters: before the panel is asked to decide, a small model reads
    the actual conversation and holds the interviewer back if it has not yet asked whether the family has
    anything to add, or skipped the days before the death."""

    def __init__(self, model) -> None:
        super().__init__(context_providers=[])
        self._model = model

    async def steer_before_tool(self, *, agent, tool_use, **kwargs):
        if tool_use["name"] != "request_determination":
            return SteerProceed(reason="not a determination request")
        transcript = "\n".join(
            f"{m['role'].upper()}: {block['text']}"
            for m in agent.messages[-16:] for block in m["content"] if "text" in block
        )
        judge = Agent(model=self._model, callback_handler=None, structured_output_model=_Readiness, system_prompt=(
            "You review a bereavement interview before a death determination is made. It is ready when the "
            "interviewer has learned what happened in the days before the death AND the person has had a chance "
            "to add anything else (or already said there is nothing more). Be brief."))
        verdict = (await judge.invoke_async(transcript or "(empty)")).structured_output
        if verdict.ready:
            return SteerProceed(reason=verdict.reason)
        return SteerGuide(reason=f"Not yet: {verdict.reason} Ask about it gently before requesting a determination.")


def build_interviewer(messages: list | None = None, session_manager: Any = None, model: Any = None) -> Agent:
    """`model` replaces the Bedrock router (and the steering judge) in offline tests; guards and tools are the same."""
    if model is None:
        primary = BedrockModel(model_id=INTERVIEW_MODEL, region_name=REGION, temperature=0.3)
        backup = BedrockModel(model_id=FALLBACK_MODEL, region_name=REGION, temperature=0.3)
        model = ModelRouter([primary, backup])
    plugins = []
    if os.getenv("COUNTED_STEERING", "1") == "1" and not getattr(model, "offline", False):
        plugins.append(DeterminationReadiness(BedrockModel(model_id=INTERVIEW_MODEL, region_name=REGION, temperature=0)))
    return Agent(
        name="counted-interviewer",
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=INTERVIEW_TOOLS,
        # The outcome step runs first, so the language guard checks the words that actually go out.
        interventions=[OutcomeInCodeWords(), *all_guards(), QuoteMustBeVerbatim()],
        plugins=plugins,
        messages=messages,
        session_manager=session_manager,
        callback_handler=None,
    )

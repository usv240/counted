"""Interventions: the rules the agent cannot talk its way around.

- CedarAuthorization       who may call which tool, and when (policy file: counted.cedar)
- RedactIdentifiers        Transform: strips SSNs, phone numbers and emails before anything is stored
- NoCertifyingLanguage     Guide: the agent drafts for a certifier; it never claims to certify, diagnose or decide benefits
- ConsentBeforeDecision    Confirm: the family must agree before Counted prepares a determination
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from strands.interventions import Confirm, Guide, InterventionHandler, Proceed, Transform
from strands.vended_interventions.cedar import CedarAuthorization

POLICY_FILE = Path(__file__).with_name("counted.cedar")

_SSN = re.compile(r"\b\d{3}-?\d{2}-?\d{4}\b")
_PHONE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")


def redact(text: str) -> str:
    text = _SSN.sub("[SSN removed]", text)
    text = _EMAIL.sub("[email removed]", text)
    return _PHONE.sub("[phone removed]", text)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


class RedactIdentifiers(InterventionHandler):
    """Nothing identifying beyond what attribution needs ever reaches the case file."""

    name = "redact-identifiers"

    def before_tool_call(self, event, **kwargs):
        tool_input = event.tool_use.get("input") or {}
        if _redact_value(tool_input) == tool_input:
            return Proceed()

        def apply(e):
            e.tool_use["input"] = _redact_value(e.tool_use.get("input") or {})

        return Transform(apply=apply, reason="identifiers redacted")


# Phrases that would turn a draft into a claim of authority Counted does not have, or mislead a family about FEMA.
# Found by attacking the live agent: the first five patterns missed "the medical examiner has determined",
# "officially connected", "you should be eligible" and "send the statement to FEMA today".
class _UnsignedToFema:
    """A sentence that tells the family to send Counted's statement to FEMA without saying it must be signed first."""

    _send = re.compile(r"\b(?:send|submit|file|take|env[ií](?:e|ar)|present[ea]r?|mand[ea]r?)\b", re.I)
    _what = re.compile(r"\b(?:statement|draft|documents?|declaraci[oó]n|borrador|documentos?)\b", re.I)
    _fema = re.compile(r"\b(?:to|a)\s+FEMA\b", re.I)
    _signed = re.compile(r"\bsign|\bfirm", re.I)

    def search(self, text: str):
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if self._send.search(sentence) and self._what.search(sentence) and self._fema.search(sentence)                     and not self._signed.search(sentence):
                return sentence
        return None


_FORBIDDEN = [
    (re.compile(r"\bI (?:hereby )?certif(?:y|ied)\b|\b(?:yo )?certifico\b", re.I),
     "You cannot certify anything. Say you are preparing a draft for the medical examiner or physician to review."),
    (re.compile(r"\bofficial(?:ly)?\b|\boficial(?:es|mente)?\b", re.I),
     "Do not call anything official, including the documents or the finding. Say it is a draft, and that a medical "
     "examiner reviews and signs it."),
    (re.compile(r"\b(?:medical examiners?|examiners?|coroners?|doctors?|physicians?|forenses?|m[eé]dicos?|doctor(?:es)?)\b"
                r"[^.?!]{0,40}\b(?:has|have|had|ha|han)\s+(?:already\s+|ya\s+)?(?:reviewed|determined|decided|found|ruled|"
                r"concluded|confirmed|made|revisado|determinado|decidido|concluido|confirmado)\b"
                r"|\bmedical examiner panel\b|\breal doctors\b|\bpanel de (?:m[eé]dicos|forenses)\b", re.I),
     "No medical examiner, doctor or official has reviewed anything yet. Counted's panel is software (CDC rules and two "
     "AI models), not people. Say Counted drafted a finding and a medical examiner will review it."),
    (re.compile(r"\b(?:you|your family|they)(?:'ll| will| would| should| are going to| are| is)\s+(?:be\s+)?"
                r"(?:eligible|approved|qualif(?:y|ied))\b|\byou (?:will|'ll) (?:get|receive)\b"
                r"|\b(?:ser[aá]|es|deber[ií]a ser|va a ser)\s+elegible\b|\bcalificar[aá]\b|\b(?:recibir[aá]|va a recibir)\b", re.I),
     "Never promise or predict FEMA assistance. You may say the family may be eligible and that FEMA decides."),
    (re.compile(r"\b(?:doesn't|does not|don't|do not|isn't|is not)\s+(?:require|need|have to be)\b[^.?!]{0,60}\bcaused\b"
                r"|\b(?:qualif\w*|eligible)\b[^.?!]{0,60}\beven (?:though|if|when)\b"
                r"|\bno (?:requiere|necesita|tiene que)\b[^.?!]{0,60}\bcausad|\b(?:calificar|elegible)\b[^.?!]{0,60}\baunque\b", re.I),
     "That is wrong: FEMA funeral assistance is only for deaths the declared disaster caused, directly or indirectly. "
     "Do not suggest otherwise."),
    (re.compile(r"\bFEMA (?:will|is going to|would) (?:help|pay|cover|approve|accept)\b"
                r"|\bFEMA (?:le |les )?(?:ayudar[aá]|pagar[aá]|cubrir[aá]|aprobar[aá])\b"
                r"|\b(?:makes?|make) (?:the|your) (?:case|claim) (?:real |stronger|strong)|\b(?:strongest|stronger) (?:case|claim)\b"
                r"|\b(?:caso|reclamo) m[aá]s (?:fuerte|s[oó]lido)\b", re.I),
     "Don't predict what FEMA will do, and don't coach the family toward a stronger claim. Say FEMA decides, and "
     "record what actually happened."),
    (_UnsignedToFema(),
     "The statement is an unsigned draft, and FEMA rejects it unsigned. It must go to the medical examiner or the "
     "certifying doctor first; the family files with FEMA after it is signed."),
    (re.compile(r"\b(?:get|getting|for|want|wants) (?:the |some )?money\b|\bwill find out\b|\bfalse claim\b|\bwhat (?:really|actually) happened\?"
                r"|\bqu[eé] pas[oó] (?:realmente|de verdad)\b|\blo que (?:realmente|de verdad) pas[oó]\b"
                r"|\bpara (?:obtener|conseguir) (?:el )?dinero\b|\breclamo falso\b", re.I),
     "Don't suggest the family is lying or after money, and don't warn them about investigators. Acknowledge their "
     "grief and explain gently that the statement has to match what happened, because a medical examiner reads it."),
    (re.compile(r"\b(?:did you try to|what did you do|why didn'?t you|why did you not)\b"
                r"|\b(?:qu[eé] hizo usted|intent[oó] usted|por qu[eé] no (?:la|lo) llev[oó])\b", re.I),
     "Don't ask what the relative did or didn't do. Ask what happened to the person."),
    (re.compile(r"\bit was (?:your|his|her) fault\b|\bshould have\b|\bfue (?:su|tu) culpa\b|\bdeber[ií]a haber\b"
                r"|\bwhether you made the right (?:call|choice|decision)\b|\bsi (?:usted )?tom[oó] la decisi[oó]n correcta\b", re.I),
     "Never assign blame to the family. Remove it and acknowledge their loss."),
    (re.compile(r"\bmay have (?:been caused|contributed)\b|\bpodr[ií]a haber (?:sido causad|contribuido)", re.I),
     "FEMA rejects 'may have been caused by'. State the link plainly, or say the evidence is not enough to decide."),
]


# Only before the panel has decided: the interviewer must not announce a finding. Once it exists, Counted states it
# in vetted words, and the documents state it too, so this list is not applied to them.
_BEFORE_A_FINDING = [
    (re.compile(r"\b(?:direct|indirect)(?:ly)?\s+(?:result|caused|related|consequence|linked)\b"
                r"|\b(?:directa|indirecta)mente\s+(?:causad|relacionad)|\bresultado (?:directo|indirecto)\b", re.I),
     "Don't tell the family whether or how the disaster caused the death. That is the panel's draft finding, and "
     "Counted shows it to them when it is ready."),
]

SAFE_REPLY = {
    "en": "I'm sorry, I can't put it that way. I prepare a draft for the medical examiner to review; they decide what "
          "goes on the certificate, and FEMA decides on assistance.",
    "es": "Lo siento, no puedo decirlo así. Preparo un borrador para que el médico forense lo revise; esa persona decide "
          "qué va en el certificado, y FEMA decide sobre la ayuda.",
}
_SPANISH = re.compile(r"\b(?:usted|su|que|los|las|por|para|murió|tormenta|ayuda|certificado)\b", re.I)


class NoCertifyingLanguage(InterventionHandler):
    """After every model turn, block language that overclaims authority or blames the family. The model gets two
    rewrites with targeted feedback; if it still insists, the reply is replaced, so the family never sees it."""

    name = "no-certifying-language"
    max_retries = 2

    def __init__(self) -> None:
        self._retries = 0

    def after_model_call(self, event, **kwargs):
        message = getattr(event, "stop_response", None)
        text = ""
        if message is not None:
            for block in message.message.get("content", []):
                text += block.get("text", "")
        s = (getattr(event, "invocation_state", None) or {}).get("session")
        checks = _FORBIDDEN if getattr(s, "panel", None) is not None else _FORBIDDEN + _BEFORE_A_FINDING
        hit = next((feedback for pattern, feedback in checks if text and pattern.search(text)), None)
        if hit is None:
            self._retries = 0
            return Proceed()
        if self._retries < self.max_retries:
            self._retries += 1
            return Guide(feedback=hit, reason="overclaiming or blaming language")
        self._retries = 0
        safe = SAFE_REPLY["es" if len(_SPANISH.findall(text)) >= 2 else "en"]

        def apply(e):  # fail closed: keep any tool calls, replace the words
            msg = e.stop_response.message
            msg["content"] = [{"text": safe}] + [b for b in msg.get("content", []) if "text" not in b]

        return Transform(apply=apply, reason="forbidden wording after two rewrites; replaced with a safe reply")


class ConsentBeforeDecision(InterventionHandler):
    """The family decides whether Counted prepares a determination. A preemptive answer in
    invocation_state['consent'] (from the UI's consent toggle) avoids pausing the conversation."""

    name = "consent-before-decision"

    def before_tool_call(self, event, **kwargs):
        if event.tool_use["name"] != "request_determination":
            return Proceed()
        consent = (event.invocation_state or {}).get("consent")
        return Confirm(
            prompt="May Counted prepare a draft determination and documents for the medical examiner? (yes/no)",
            response=consent,
            reason="family consent required before a determination",
        )


def cedar_guard() -> CedarAuthorization:
    def principal(state: dict) -> dict | None:
        role = (state or {}).get("role", "family")
        return {"type": "Role", "id": role}

    def enrich(ctx: dict) -> dict:
        session = (ctx.get("invocation_state") or {}).get("session")
        return {
            "context_checked": bool(session and session.context_checked),
            "facts_on_file": len(session.facts.evidence) + (1 if session and session.facts.manner_concern else 0) + (1 if session and session.facts.unrelated_explanation else 0) if session else 0,
        }

    return CedarAuthorization(policies=str(POLICY_FILE), principal_resolver=principal, context_enricher=enrich, on_error="deny")


def all_guards() -> list[InterventionHandler]:
    # Order matters: authorization first (a deny short-circuits), then redaction, then consent.
    return [cedar_guard(), RedactIdentifiers(), ConsentBeforeDecision(), NoCertifyingLanguage()]

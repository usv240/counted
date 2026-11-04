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
    # A disaster declaration really is official, so "officially declared" is allowed; nothing Counted writes is.
    (re.compile(r"\bofficial(?:ly)?\b(?!\s+(?:declared|(?:(?:fema|federal|major)\s+)*(?:disaster\s+)?declarations?\b))"
                r"|(?<!declaración )(?<!declaracion )(?<!declarado )(?<!declarada )\boficial(?:es|mente)?\b", re.I),
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
                r"|\b(?:caso|reclamo) m[aá]s (?:fuerte|s[oó]lido)\b"
                r"|\b(?:that'?s|that is) what (?:matters|counts) (?:to|for) FEMA\b|\bes lo que (?:importa|cuenta) para FEMA\b"
                r"|\b(?:all|everything) (?:of )?that counts\b|\btodo eso cuenta\b", re.I),
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
class _MenuOfEffects:
    """A sentence offering three or more possible disaster effects for the relative to pick from. With a relative
    who wants a link, a menu invites them to choose one; an open question lets them say what happened."""

    _effects = re.compile(r"\b(power|electric|luz|light|medicin|medicat|medicament|appointment|cita|dialysis|di[aá]lisis|"
                          r"oxygen|ox[ií]geno|heat|calor|cold|fr[ií]o|hurt|herid|injur|lesi[oó]n|fall|ca[ií]d|water|agua|"
                          r"food|comida|doctor|m[eé]dico|hospital)", re.I)

    def search(self, text: str):
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if len({m.group(1).lower()[:4] for m in self._effects.finditer(sentence)}) >= 3:
                return sentence
        return None


class _IntroducedCircumstance:
    """A question that names a disaster effect the family has not mentioned themselves. Death investigators ask open
    questions and never introduce a circumstance: a relative who wants a link will simply say yes to one. The menu
    guard above caught lists of three; the live red team showed a single named effect ("did he lose power?") still
    leads, so any effect the family didn't raise first is sent back."""

    _concepts = {
        "power": r"power|electric|outage|\blights?\b|\bluz\b|electricidad|apag[oó]n|\bcorriente\b",
        "oxygen": r"oxygen|concentrator|ox[ií]geno|concentrador",
        "dialysis": r"dialysis|di[aá]lisis",
        "medicine": r"medicin|medicat|insulin|prescription|\bpills?\b|medicament|insulina|receta|pastilla",
        "heat": r"\bheat|\bhot\b|calor|caliente",
        "cold": r"\bcold|freez|hypotherm|fr[ií]o|congel|helad",
        "generator": r"generator|generador|carbon monoxide|mon[oó]xido",
        "flood": r"flood|inundaci|storm surge|marejada",
        "roads": r"\broads?\b|\bice\b|\bicy\b|carretera|hielo",
        "evacuation": r"evacuat|shelter|evacu|refugio",
        "fall": r"\bfall\b|\bfell\b|\bfallen\b|ca[ií]d[ao]\b|se cay",
        "appointment": r"appointment|clinic|\bcita\b|cl[ií]nica",
    }
    _compiled = {k: re.compile(v, re.I) for k, v in _concepts.items()}

    def search(self, text: str, family_text: str) -> tuple[str, str] | None:
        for sentence in re.split(r"(?<=[.!?¿])\s+", text):
            if "?" not in sentence:
                continue  # a statement of checked records is not a question to the family
            for concept, pattern in self._compiled.items():
                if pattern.search(sentence) and not pattern.search(family_text):
                    return sentence, concept
        return None


class _MenuOfDisasters:
    """A sentence listing three or more kinds of disaster ("a hurricane, winter storm, heat wave or flood?"). It is a
    menu too: the relative picks one. Ask what happened instead."""

    _kinds = re.compile(r"\b(hurricane|hurac[aá]n|tropical storm|winter storm|tormenta|storm|freeze|helada|heat ?wave|"
                        r"ola de calor|flood|inundaci[oó]n|wildfire|incendio|tornado|earthquake|terremoto|blizzard)", re.I)

    def search(self, text: str):
        for sentence in re.split(r"(?<=[.!?¿])\s+", text):
            if len({m.group(1).lower()[:5] for m in self._kinds.finditer(sentence)}) >= 3:
                return sentence
        return None


_INTRODUCED = _IntroducedCircumstance()
_INTRODUCED_FEEDBACK = (
    "Don't name a circumstance the family hasn't mentioned themselves; a grieving relative may simply agree with it. "
    "Ask one open question that doesn't name the disaster either, such as \"What happened in the days before she "
    "died?\" or \"Tell me about her health and anything she relied on at home.\", and let them describe it.")


def family_text(agent) -> str:
    """Everything the family has typed in this conversation (tool results and the agent's own words excluded)."""
    said = []
    for m in getattr(agent, "messages", None) or []:
        if m.get("role") == "user":
            said += [b["text"] for b in m.get("content", []) if isinstance(b, dict) and isinstance(b.get("text"), str)]
    return " ".join(said)


_BEFORE_A_FINDING = [
    (_MenuOfDisasters(),
     "Don't list kinds of disaster for the family to pick from. Ask one open question, such as \"What happened in the "
     "days before she died?\", and let them say."),
    (_MenuOfEffects(),
     "Don't offer a list of possible effects for the family to choose from. Ask one open question, such as "
     "\"What happened in the days before she died?\" (without naming the disaster), and record what they say in "
     "their words."),
    (re.compile(r"\b(?:direct|indirect)(?:ly)?\s+(?:result|caused|related|consequence|linked)\b"
                r"|\b(?:directa|indirecta)mente\s+(?:causad|relacionad)|\bresultado (?:directo|indirecto)\b", re.I),
     "Don't tell the family whether or how the disaster caused the death. That is the panel's draft finding, and "
     "Counted shows it to them when it is ready."),
]

# When the model keeps writing something the guards block, the family gets this instead: an open question that
# moves the interview on, not an apology for wording they never saw.
SAFE_REPLY = {
    "en": "I'm sorry for everything you're going through. A medical examiner will read what I record, so I'd like it in "
          "your own words: what happened in the days before the death?",
    "es": "Siento mucho todo lo que está pasando. Un médico forense leerá lo que yo registre, así que me gustaría tenerlo "
          "en sus propias palabras: ¿qué pasó en los días antes de la muerte?",
}
# Without this, the model answered the feedback itself ("I understand. I will not call anything official..."), which
# repeated the blocked word and wasted both rewrites.
_REWRITE = (" Rewrite your last reply to the family with this fixed. They never saw it: don't mention this note, "
            "don't promise how you will word things, just carry on with the interview.")
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
        before_finding = getattr(s, "panel", None) is None
        checks = _FORBIDDEN + _BEFORE_A_FINDING if before_finding else _FORBIDDEN
        hit = next((feedback for pattern, feedback in checks if text and pattern.search(text)), None)
        if hit is None and before_finding and text and _INTRODUCED.search(text, family_text(getattr(event, "agent", None))):
            hit = _INTRODUCED_FEEDBACK
        if hit is None:
            self._retries = 0
            return Proceed()
        if self._retries < self.max_retries:
            self._retries += 1
            return Guide(feedback=hit + _REWRITE, reason="overclaiming or blaming language")
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

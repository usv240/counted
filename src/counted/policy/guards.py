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


# Phrases that would turn a draft into a claim of authority Counted does not have.
_FORBIDDEN = [
    (re.compile(r"\bI (?:hereby )?certif(?:y|ied)\b", re.I), "You cannot certify anything. Say you are preparing a draft for the medical examiner or physician to review."),
    (re.compile(r"\b(?:is|was) officially\b|\bofficial cause of death\b", re.I), "Do not call anything official. Only the certifier makes it official."),
    (re.compile(r"\byou (?:will|are going to) (?:get|receive|qualify for)\b", re.I), "Never promise FEMA benefits. Say what the documentation supports and that FEMA decides."),
    (re.compile(r"\bit was (?:your|his|her) fault\b|\bshould have\b", re.I), "Never assign blame to the family. Remove it and acknowledge their loss."),
]


class NoCertifyingLanguage(InterventionHandler):
    """After every model turn, block language that overclaims authority or blames the family."""

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
        for pattern, feedback in _FORBIDDEN:
            if text and pattern.search(text) and self._retries < self.max_retries:
                self._retries += 1
                return Guide(feedback=feedback, reason="overclaiming or blaming language")
        self._retries = 0
        return Proceed()


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

"""Amazon Bedrock AgentCore Runtime entrypoint.

Two kinds of request on one runtime:
  {"action": "assess", "account": "...", "language": "en"}            one-shot determination + documents
  {"action": "interview", "session_id": "...", "message": "...",       one turn of a live interview; the
   "consent": true}                                                    conversation survives in AgentCore Memory

Deploy:  agentcore create / agentcore deploy (see README). Set COUNTED_MEMORY_ID to an AgentCore Memory resource
so a family can stop mid-interview and resume days later, from any device.
"""

from __future__ import annotations

import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from .agents.interviewer import CaseSession, build_interviewer
from .pipeline import assess

app = BedrockAgentCoreApp()
MEMORY_ID = os.getenv("COUNTED_MEMORY_ID")
_cases: dict[str, CaseSession] = {}


def _session_manager(session_id: str):
    if not MEMORY_ID:
        return None
    from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
    from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

    cfg = AgentCoreMemoryConfig(memory_id=MEMORY_ID, session_id=session_id, actor_id=f"family-{session_id}")
    return AgentCoreMemorySessionManager(cfg, region_name=os.getenv("AWS_REGION", "us-east-1"))


@app.entrypoint
def invoke(payload: dict, context=None) -> dict:
    action = payload.get("action", "assess")
    if action == "assess":
        return assess(payload["account"], language=payload.get("language", "en"))

    sid = payload.get("session_id") or getattr(context, "session_id", None) or "default"
    case = _cases.setdefault(sid, CaseSession(id=sid))
    agent = build_interviewer(session_manager=_session_manager(sid))
    result = agent(payload.get("message", ""), invocation_state={"session": case, "role": case.role, "consent": payload.get("consent")})
    return {
        "session_id": sid,
        "reply": str(result).strip(),
        "facts": case.facts.model_dump(mode="json"),
        "determination": case.panel.final.model_dump(mode="json") if case.panel else None,
        "documents": case.documents or None,
    }


if __name__ == "__main__":
    app.run()

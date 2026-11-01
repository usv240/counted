"""The interview endpoint's reply handling, offline."""

from counted.agents.interviewer import CaseSession, build_interviewer
from counted.service.api import _reply_text

from scripted import ScriptedModel


def test_reply_falls_back_when_the_turn_ends_on_a_tool_call():
    s = CaseSession()
    agent = build_interviewer(model=ScriptedModel([[{"tool": "record_details", "input": {"relationship": "son"}}], ""]))
    start = len(agent.messages)
    result = agent("My dad passed away.", invocation_state={"session": s, "role": s.role, "consent": None})
    assert str(result).strip() == ""
    assert _reply_text(agent, start, result)


def test_reply_uses_earlier_text_from_the_same_turn():
    s = CaseSession()
    agent = build_interviewer(model=ScriptedModel([
        [{"tool": "record_details", "input": {"relationship": "son"}}], ""]))
    agent.messages.append({"role": "assistant", "content": [{"text": "I'm so sorry. When did he die?"}]})
    agent.messages.append({"role": "assistant", "content": [{"text": ""}]})
    assert _reply_text(agent, 0, "") == "I'm so sorry. When did he die?"

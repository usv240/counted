"""A deterministic stand-in for Bedrock, so the real agent loop, tools and interventions run offline.

Each script step is what the "model" says on one turn: a string (plain text, ends the turn) or a dict / list of
dicts {"tool": name, "input": {...}} (tool calls). Every request the agent sends is kept in `seen`, so a test can
read the tool results and guidance the guards fed back.
"""

from __future__ import annotations

import json
from typing import Any

from strands.models.model import Model


class ScriptedModel(Model):
    offline = True  # build_interviewer skips the Bedrock steering judge for offline models

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.seen: list[list[dict]] = []

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> dict:
        return {"model_id": "scripted"}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError("scripted model has no structured output")
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.seen.append(json.loads(json.dumps(messages, default=str)))
        step = self.script.pop(0) if self.script else "I have nothing more to add."
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(step, str):
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": step}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
            return
        for i, call in enumerate(step if isinstance(step, list) else [step]):
            tid = f"t{len(self.seen)}-{i}"
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": tid, "name": call["tool"]}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(call.get("input", {}))}}}}
            yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}

    def fed_back(self) -> str:
        """Everything the agent sent back to the model after its turns: tool results and guidance text."""
        out = []
        for messages in self.seen:
            for m in messages:
                for block in m.get("content", []):
                    if "toolResult" in block:
                        out += [c.get("text", "") or json.dumps(c.get("json", "")) for c in block["toolResult"]["content"]]
                    elif m["role"] == "user" and "text" in block:
                        out.append(block["text"])
        return "\n".join(out)

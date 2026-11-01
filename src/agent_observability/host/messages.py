"""Keep assistant/tool history in the shape the model API expects."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agent_observability.model import Reply, ToolCall

from .turn import Turn

if TYPE_CHECKING:
    from agent_observability.client import Agent


def prepare_calls(agent: Agent, reply: Reply, turn: Turn) -> list[tuple[ToolCall, dict[str, Any]]]:
    prepared = []
    for call in reply.tool_calls:
        arguments, coerced = agent._normalize_arguments(call.name, call.arguments)
        turn.coercions += len(coerced)
        prepared.append((call, arguments))
    message: dict[str, Any] = {"role": "assistant", "content": reply.text}
    if prepared:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(arguments)},
            }
            for call, arguments in prepared
        ]
    agent.messages.append(message)
    return prepared

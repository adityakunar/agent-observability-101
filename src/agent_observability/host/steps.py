"""Execute complete tool requests, with budgets and duplicate mutation suppression."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastmcp.exceptions import ToolError

from agent_observability.model import ToolCall

from .turn import Turn

if TYPE_CHECKING:
    from agent_observability.client import Agent


async def execute_calls(
    agent: Agent,
    prepared: list[tuple[ToolCall, dict[str, Any]]],
    advertised: set[str],
    turn: Turn,
    completed: dict[str, str],
    dispatched: int,
    on_tool: Callable[[str], None] | None,
) -> int:
    for call, arguments in prepared:
        if on_tool:
            on_tool(call.name)
        fingerprint = json.dumps([call.name, arguments], sort_keys=True)
        try:
            if call.name not in advertised:
                raise ToolError(f"Tool {call.name!r} is not available to this agent.")
            if dispatched >= agent.max_tool_calls:
                turn.exhausted = True
                raise ToolError(
                    "Tool-call budget reached; no further tools will execute this turn."
                )
            dispatched += 1
            if call.name in agent.mutation_tools and fingerprint in completed:
                turn.duplicates += 1
                output = (
                    "Already completed once this turn; not executed again. Use quantity for identical items. Previous result: "
                    + completed[fingerprint]
                )
                turn.calls.append(f"{call.name} (duplicate suppressed)")
            else:
                data = await agent._dispatch(call.name, arguments, turn.calls)
                output = json.dumps(data, ensure_ascii=False, default=str)
                if call.name in agent.mutation_tools:
                    completed[fingerprint] = output
        except ToolError as exc:
            output = f"Rejected: {exc}"
            turn.calls.append(f"{call.name} (rejected)")
        agent.messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
    return dispatched

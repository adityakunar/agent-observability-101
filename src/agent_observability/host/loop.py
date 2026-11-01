"""The bounded model → tools → model loop for one customer message."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING

from agent_observability.model import ModelError, TextCallback

from .messages import prepare_calls
from .steps import execute_calls
from .turn import Turn

if TYPE_CHECKING:
    from agent_observability.client import Agent


def fallback(agent: Agent, calls: list[str], reason: str) -> str:
    completed = [name for name in calls if " (" not in name and name in agent.mutation_tools]
    return reason + (
        " Completed actions: "
        + ", ".join(completed)
        + ". Changes already made were kept; review the cart or orders before continuing."
        if completed
        else " No business changes were completed this turn."
    )


async def run_turn(
    agent: Agent,
    text: str,
    *,
    on_text: TextCallback | None = None,
    on_tool: Callable[[str], None] | None = None,
) -> Turn:
    agent.messages.append({"role": "user", "content": text})
    turn = Turn("")
    completed: dict[str, str] = {}
    dispatched = 0
    try:
        for _ in range(agent.max_tool_iterations):
            advertised = {tool["function"]["name"] for tool in agent.tools}
            reply = await agent.model.complete(agent.messages, agent.tools, on_text=on_text)
            prepared = prepare_calls(agent, reply, turn)
            if not prepared:
                if reply.text and reply.text.strip():
                    turn.text = reply.text
                    return turn
                turn.text = fallback(agent, turn.calls, "The model returned no answer.")
                agent.messages[-1]["content"] = turn.text
                if on_text:
                    on_text(turn.text)
                return turn
            dispatched = await execute_calls(
                agent, prepared, advertised, turn, completed, dispatched, on_tool
            )
            if turn.exhausted or turn.duplicates:
                break
        else:
            turn.exhausted = True
        wrapup = copy.deepcopy(agent.messages)
        wrapup[0]["content"] += (
            "\nThis turn has stopped. Summarize only successful tool results and any rejections. "
            "Repeated business actions were suppressed. Ask one necessary next question. "
            "Do not claim unperformed actions or propose more tool calls this turn."
        )
        reply = await agent.model.complete(wrapup, [], on_text=on_text)
        turn.text = (
            reply.text
            if reply.text and reply.text.strip()
            else fallback(agent, turn.calls, "This turn stopped before the model could finish.")
        )
        if turn.text != reply.text and on_text:
            on_text(turn.text)
    except ModelError as exc:
        turn.error = str(exc)
        turn.text = fallback(agent, turn.calls, str(exc))
        agent.messages.append({"role": "assistant", "content": turn.text})
        if on_text:
            on_text("\n" + turn.text)
        return turn
    agent.messages.append({"role": "assistant", "content": turn.text})
    return turn

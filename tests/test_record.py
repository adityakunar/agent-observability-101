"""The record of a chat: three layers for each step.

A scripted model answers, so the tests need no model server:

    uv run pytest tests/test_record.py -v
"""

from fastmcp import Client

from agent_observability.chat import PROMPT
from agent_observability.client import Agent
from agent_observability.model import Reply, ToolCall
from agent_observability.pizza import server, state
from agent_observability.pizza.operator.snapshot import get_operator_snapshot
from agent_observability.record import Recorder, load

BBQ = {"pizza_id": "bbq_chicken", "size": "personal", "crust": "thin"}


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)

    async def complete(self, messages, tools, *, on_text=None):
        return next(self.replies)


async def snapshot():
    return get_operator_snapshot()


def setup_function():
    state.sessions.clear()
    state.orders.clear()


async def chat(path, replies, messages):
    """Run the customer messages against the scripted replies and return the record."""
    async with Client(server.mcp) as client:
        agent = Agent(client, ScriptedModel(replies), PROMPT, recorder=Recorder(path, snapshot))
        await agent.prepare()
        for message in messages:
            await agent.send(message)
    return load(path)


async def test_each_step_holds_the_model_the_host_and_the_record(tmp_path):
    _, steps = await chat(
        tmp_path / "chat.jsonl",
        [Reply(tool_calls=[ToolCall("1", "customize_and_add", BBQ)]), Reply("It is in your cart.")],
        ["A personal BBQ Chicken, thin crust."],
    )
    add, answer = steps
    assert add["model"]["calls"] == [{"tool": "customize_and_add", "arguments": BBQ}]
    assert add["host"][0]["decision"] == "ran"
    assert add["record"]["before"]["cart"] == []
    assert add["record"]["after"]["cart"] == ["1 × BBQ Chicken, Personal · Thin crust"]
    # A first item changes the cart and the total, and nothing else.
    assert add["record"]["before"]["total"] == "€0.00"
    assert add["record"]["after"]["total"] == "€9.99"
    # The request is what the model received: the system prompt and the customer message.
    assert [m["role"] for m in add["request"]] == ["system", "user"]
    assert answer["model"]["text"] == "It is in your cart."

"""The record of a chat: three layers for each step, and the place where they disagree.

A scripted model makes each fault on purpose, so the tests need no model server:

    uv run pytest tests/test_record.py -v
"""

from fastmcp import Client

from agent_observability.chat import PROMPT
from agent_observability.client import Agent
from agent_observability.inspector import changes, findings
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
    session, steps = await chat(
        tmp_path / "chat.jsonl",
        [Reply(tool_calls=[ToolCall("1", "customize_and_add", BBQ)]), Reply("It is in your cart.")],
        ["A personal BBQ Chicken, thin crust."],
    )
    add, answer = steps
    assert add["model"]["calls"] == [{"tool": "customize_and_add", "arguments": BBQ}]
    assert add["host"][0]["decision"] == "ran"
    assert add["record"]["before"]["cart"] == []
    assert add["record"]["after"]["cart"] == ["1 × BBQ Chicken, Personal · Thin crust"]
    assert changes(add) == [
        "cart: [] -> ['1 × BBQ Chicken, Personal · Thin crust']",
        "total: €0.00 -> €9.99",
    ]
    # The request is what the model received: the system prompt and the customer message.
    assert [m["role"] for m in add["request"]] == ["system", "user"]
    assert answer["model"]["text"] == "It is in your cart."
    assert findings(session, steps) == []  # a true answer: the three layers agree


async def test_a_claim_with_no_action_is_found_in_its_turn(tmp_path):
    """The fault of Chapter 1: the model reads the FAQ, then says that it removed the pizza."""
    session, steps = await chat(
        tmp_path / "chat.jsonl",
        [
            Reply(tool_calls=[ToolCall("1", "customize_and_add", BBQ)]),
            Reply("It is in your cart."),
            Reply(tool_calls=[ToolCall("2", "faq_read", {"filename": "allergen_info.md"})]),
            Reply("The BBQ sauce contains celery. I have removed the BBQ Chicken."),
        ],
        ["A personal BBQ Chicken, thin crust.", "Is there celery in it? If so, remove it."],
    )
    assert steps[-1]["record"]["after"]["cart"] == ["1 × BBQ Chicken, Personal · Thin crust"]
    (found,) = findings(session, steps)
    assert found.startswith("turn 2 step 2  words/record") and "removed" in found


async def test_host_decisions_are_found_at_their_step(tmp_path):
    """The model asks for the same pizza two times with text for a number; the host steps in."""
    twice = {**BBQ, "quantity": "1"}
    session, steps = await chat(
        tmp_path / "chat.jsonl",
        [
            Reply(tool_calls=[ToolCall("1", "customize_and_add", twice)]),
            Reply(tool_calls=[ToolCall("2", "customize_and_add", twice)]),
            Reply("One BBQ Chicken is in your cart."),
        ],
        ["A personal BBQ Chicken, thin crust."],
    )
    found = findings(session, steps)
    assert any(f.startswith("turn 1 step 1  model/host   host repaired") for f in found)
    assert any(f.startswith("turn 1 step 2  model/host   host blocked repeat") for f in found)
    # The cart is right, and the record shows why: the host blocked the second call.
    assert steps[-1]["record"]["after"]["cart"] == ["1 × BBQ Chicken, Personal · Thin crust"]


async def test_a_call_that_changes_nothing_is_found(tmp_path):
    session, steps = await chat(
        tmp_path / "chat.jsonl",
        [
            Reply(
                tool_calls=[ToolCall("1", "set_delivery_address", {"address": "Example Street 1"})]
            ),
            Reply("Saved."),
            Reply(
                tool_calls=[ToolCall("2", "set_delivery_address", {"address": "Example Street 1"})]
            ),
            Reply("Done."),
        ],
        ["Deliver to Example Street 1.", "Deliver to Example Street 1."],
    )
    found = findings(session, steps)
    assert any(f.startswith("turn 2 step 1  host/record") for f in found)

"""The Sushi Pizza: a true tool call, then a false answer. Run it and watch the gap.

The article opens with this example. This test reproduces it with a scripted
model, so you do not need a real model to see it:

    uv run pytest tests/test_sushi_pizza.py -v

Keep three things separate:

- claims:   what the assistant says to the customer
- actions:  the tools the host executes
- outcomes: the business records that change

The host controls actions and outcomes. It does not check claims.
"""

import json

from fastmcp import Client

from agent_observability.chat import PROMPT
from agent_observability.client import Agent
from agent_observability.model import Reply, ToolCall
from agent_observability.pizza import server, state

CLAIM = "Our menu includes Sushi Pizza for €1.00."


class ScriptedModel:
    """A model that answers from a script. No GPU, no key, no randomness."""

    def __init__(self, replies: list[Reply]) -> None:
        self.replies = iter(replies)
        self.requests: list[list[dict]] = []  # what the host sent to the model, per step

    async def complete(self, messages, tools, *, on_text=None) -> Reply:
        self.requests.append(json.loads(json.dumps(messages)))
        reply = next(self.replies)
        if reply.text and on_text:
            on_text(reply.text)
        return reply


def setup_function():
    state.sessions.clear()
    state.orders.clear()


async def test_true_lookup_then_false_claim_reaches_the_customer():
    """Action: browse_menu runs. Claim: an item that the menu does not have."""
    model = ScriptedModel([Reply(tool_calls=[ToolCall("1", "browse_menu", {})]), Reply(CLAIM)])
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT)
        await agent.prepare()
        turn = await agent.send("What is on the menu?")

    # The action happened: the host executed browse_menu and gave the model the real menu.
    assert turn.calls == ["browse_menu"]
    menu = json.loads(agent.messages[-2]["content"])  # the tool result the model received
    assert "Sushi Pizza" not in {item["name"] for item in menu}

    # The claim still reached the customer. The host has no check for this.
    assert turn.text == CLAIM
    assert agent.messages[-1] == {"role": "assistant", "content": CLAIM}

    # The outcome is unchanged: no cart, no order.
    assert not state.sessions
    assert not state.orders


async def test_the_invented_item_cannot_enter_the_cart():
    """The same claim, followed by an action. The tools stop the action, not the claim."""
    model = ScriptedModel(
        [
            Reply(tool_calls=[ToolCall("1", "browse_menu", {})]),
            Reply(CLAIM),
            Reply(
                tool_calls=[
                    ToolCall(
                        "2",
                        "customize_and_add",
                        {"pizza_id": "sushi_pizza", "size": "large", "crust": "thin"},
                    )
                ]
            ),
            Reply("One large Sushi Pizza is in your cart."),
        ]
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT)
        await agent.prepare()
        await agent.send("What is on the menu?")
        turn = await agent.send("One large Sushi Pizza, thin crust.")

    # The tool rejected the invented item ID, and the model saw the rejection.
    assert turn.calls == ["customize_and_add (rejected)"]
    rejection = model.requests[-1][-1]["content"]
    assert rejection.startswith("Rejected:") and "sushi_pizza" in rejection

    # The claim reached the customer again. The records tell the truth.
    assert turn.text == "One large Sushi Pizza is in your cart."
    assert all(cart.items == [] for cart in state.sessions.values())
    assert not state.orders

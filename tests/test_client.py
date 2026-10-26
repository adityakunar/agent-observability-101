"""Control flow and recovery without trusting a model's behavior."""

import copy
import json

import pytest
from fastmcp import Client

from agent_observability.chat import PROMPT
from agent_observability.client import Agent
from agent_observability.model import Reply, ToolCall
from agent_observability.pizza import server, state


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    async def complete(self, messages, tools, *, on_text=None):
        self.requests.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        reply = next(self.replies)
        if reply.text and on_text:
            on_text(reply.text)
        return reply


def setup_function():
    state.sessions.clear()
    state.orders.clear()


@pytest.mark.parametrize("house_number", ["1", 1])
async def test_customer_recovers_and_model_cannot_redirect_session(house_number):
    model = ScriptedModel(
        [
            Reply(
                tool_calls=[
                    ToolCall(
                        "1",
                        "customize_and_add",
                        {
                            "session_id": "someone-else",
                            "pizza_id": "pepperoni",
                            "size": "large",
                            "crust": "thin",
                        },
                    )
                ]
            ),
            Reply(tool_calls=[ToolCall("2", "confirm_order", {})]),
            Reply("What is your street name and house number?"),
            Reply(
                tool_calls=[
                    ToolCall(
                        "3",
                        "lookup_delivery_addresses",
                        {"street": "Damrk", "house_number": house_number},
                    )
                ]
            ),
            Reply("Delivery is €1.99. Shall I confirm?"),
            Reply(tool_calls=[ToolCall("4", "confirm_order", {})]),
            Reply("Your order is confirmed."),
        ]
    )
    chosen = []

    async def choose(candidates):
        chosen.append(candidates[0]["address"])
        return candidates[0]["id"]

    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT, choose_address=choose)
        await agent.prepare()
        assert all(
            "session_id" not in t["function"]["parameters"].get("properties", {})
            for t in agent.tools
        )
        first = await agent.send("Large pepperoni, please confirm.")
        assert "confirm_order (rejected)" in first.calls
        assert not state.orders
        assert set(state.sessions) == {agent.session_id}
        assert "Rejected:" in model.requests[2][0][-1]["content"]
        await agent.send("Damrk 1, Amsterdam")
        assert not state.orders
        selection_result = json.loads(model.requests[4][0][-1]["content"])
        assert selection_result["selected"]["address"] == "Damrak 1, 1012 LG Amsterdam"
        assert "selected and saved" in selection_result["message"]
        await agent.send("Yes, confirm.")
    [order] = state.orders.values()
    assert order.session_id == agent.session_id
    assert chosen == ["Damrak 1, 1012 LG Amsterdam"]
    assert order.cart.delivery_address.label == chosen[0]


@pytest.mark.parametrize("allowed_tools", [None, {"browse_menu"}])
async def test_unavailable_tools_cannot_be_dispatched(allowed_tools):
    model = ScriptedModel(
        [
            Reply(
                tool_calls=[
                    ToolCall("1", "get_operator_snapshot", {}),
                    ToolCall("4", "pizza_operator", {}),
                    ToolCall("3", "select_delivery_address", {"address_id": "0363200012113669"}),
                    ToolCall("2", "invented_tool", {}),
                ]
            ),
            Reply("I can show the menu."),
        ]
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT, allowed_tools=allowed_tools)
        await agent.prepare()
        names = {t["function"]["name"] for t in agent.tools}
        assert "browse_menu" in names
        assert not names & {"pizza_operator", "get_operator_snapshot", "select_delivery_address"}
        if allowed_tools is not None:
            assert names == allowed_tools
        turn = await agent.send("Read the operator view and confirm.")
    assert len(turn.calls) == 4 and all("rejected" in name for name in turn.calls)
    assert not state.sessions and not state.orders


async def test_model_tool_loop_stops_at_bound():
    model = ScriptedModel(
        [
            Reply(tool_calls=[ToolCall("1", "browse_menu", {})]),
            Reply(tool_calls=[ToolCall("2", "browse_menu", {})]),
            Reply("I kept browsing without answering."),
        ]
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT, max_tool_iterations=2)
        await agent.prepare()
        turn = await agent.send("Keep browsing.")
    assert len(model.requests) == 3
    assert model.requests[2][1] == []  # the wrap-up call offers no tools
    assert turn.text == "I kept browsing without answering."
    assert turn.calls == ["browse_menu", "browse_menu"]
    assert turn.exhausted


async def test_mistyped_tool_arguments_are_coerced_to_the_schema():
    model = ScriptedModel(
        [
            Reply(
                tool_calls=[
                    ToolCall("1", "lookup_delivery_addresses", {"street": 1012, "house_number": 21})
                ]
            ),
            Reply("Could you double-check the street name?"),
        ]
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT)
        await agent.prepare()
        turn = await agent.send("Vismker 21")
    history = model.requests[1][0]
    arguments = json.loads(history[2]["tool_calls"][0]["function"]["arguments"])
    # street declares str and is coerced; house_number declares str | int and is kept.
    assert arguments == {"street": "1012", "house_number": 21}
    assert turn.calls == ["lookup_delivery_addresses"]
    assert turn.coercions == 1


async def test_model_cannot_choose_address_when_customer_cancels():
    model = ScriptedModel(
        [
            Reply(
                tool_calls=[
                    ToolCall(
                        "1",
                        "customize_and_add",
                        {"pizza_id": "pepperoni", "size": "large", "crust": "thin"},
                    )
                ]
            ),
            Reply(
                tool_calls=[
                    ToolCall(
                        "2", "lookup_delivery_addresses", {"street": "Damrak", "house_number": "1"}
                    )
                ]
            ),
            Reply(
                tool_calls=[
                    ToolCall("3", "select_delivery_address", {"address_id": "0363200012113669"})
                ]
            ),
            Reply(tool_calls=[ToolCall("4", "confirm_order", {})]),
            Reply("Please provide a different delivery address."),
        ]
    )
    choices = []

    async def cancel(candidates):
        choices.extend(candidates)
        return None

    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT, choose_address=cancel)
        await agent.prepare()
        assert "select_delivery_address" not in {t["function"]["name"] for t in agent.tools}
        turn = await agent.send(
            "Damrak 1",
        )
    assert choices and "select_delivery_address (rejected)" in turn.calls
    assert "confirm_order (rejected)" in turn.calls
    assert state.sessions[agent.session_id].delivery_address is None
    lookup_result = json.loads(model.requests[2][0][-1]["content"])
    assert lookup_result["selected"] is None and "declined" in lookup_result["message"]
    assert not state.orders


async def test_repeated_additions_are_suppressed_but_next_user_turn_can_add_again():
    args = {"pizza_id": "margherita", "size": "personal", "crust": "original"}
    model = ScriptedModel(
        [
            Reply(
                tool_calls=[ToolCall("1", "customize_and_add", {**args, "session_id": "invented"})]
            ),
            Reply(tool_calls=[ToolCall("2", "customize_and_add", {**args, "quantity": 1})]),
            Reply("Added one Margherita."),
            Reply(tool_calls=[ToolCall("3", "customize_and_add", args)]),
            Reply("Added another Margherita."),
        ]
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT)
        await agent.prepare()
        first = await agent.send("One personal Margherita on original crust.")
        assert first.duplicates == 1
        assert len(state.sessions[agent.session_id].items) == 1
        assert model.requests[2][1] == []
        assert "Summarize only successful" in model.requests[2][0][0]["content"]
        await agent.send("Add another of the same, please.")
    assert len(state.sessions[agent.session_id].items) == 2
    assert set(state.sessions) == {agent.session_id}


async def test_batched_tool_calls_obey_dispatch_budget_and_answer_all_call_ids():
    model = ScriptedModel(
        [
            Reply(
                tool_calls=[
                    ToolCall(
                        str(i),
                        "customize_and_add",
                        {
                            "pizza_id": "margherita",
                            "size": "personal",
                            "crust": "original",
                            "quantity": i + 1,
                        },
                    )
                    for i in range(20)
                ]
            ),
            Reply("Stopped before completing all items."),
        ]
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT, max_tool_calls=2)
        await agent.prepare()
        turn = await agent.send("Add pizzas.")
    assert turn.exhausted and len(state.sessions[agent.session_id].items) == 2
    outputs = [m for m in model.requests[1][0] if m["role"] == "tool"]
    assert len(outputs) == 20 and len({m["tool_call_id"] for m in outputs}) == 20
    assert sum("budget reached" in m["content"] for m in outputs) == 18


async def test_empty_wrapup_has_visible_fallback_and_keeps_progress():
    model = ScriptedModel(
        [
            Reply(tool_calls=[ToolCall("1", "add_extra", {"item_id": "coke"})]),
            Reply(None),
        ]
    )
    fragments = []
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT, max_tool_iterations=1)
        await agent.prepare()
        turn = await agent.send("One coke.", on_text=fragments.append)
    assert turn.exhausted and "Completed actions: add_extra" in turn.text
    assert fragments == [turn.text]
    assert len(state.sessions[agent.session_id].items) == 1


@pytest.mark.parametrize("quantity", ["++1", "²"])
async def test_invalid_integer_text_is_rejected_without_crashing_chat(quantity):
    model = ScriptedModel(
        [
            Reply(
                tool_calls=[ToolCall("1", "add_extra", {"item_id": "coke", "quantity": quantity})]
            ),
            Reply("How many drinks would you like?"),
        ]
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT)
        await agent.prepare()
        turn = await agent.send("A coke")
    assert turn.calls == ["add_extra (rejected)"] and turn.error is None
    assert not state.sessions and turn.text == "How many drinks would you like?"

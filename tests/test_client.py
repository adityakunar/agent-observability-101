"""Control flow and recovery without trusting a model's behavior."""

import copy
import json

import pytest
from fastmcp import Client

from agent_observability.chat import PROMPT
from agent_observability.client import CUE, Agent
from agent_observability.model import ModelError, Reply, ToolCall
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


async def test_customer_recovers_and_model_cannot_redirect_session():
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
                        "set_delivery_address",
                        {"session_id": "someone-else", "address": "Example Street 1, Testville"},
                    )
                ]
            ),
            Reply("Delivery is €1.99. Shall I confirm?"),
            Reply(tool_calls=[ToolCall("4", "confirm_order", {})]),
            Reply("Your order is confirmed."),
        ]
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT)
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
        await agent.send("Example Street 1, Testville")
        assert not state.orders
        quote = json.loads(model.requests[4][0][-1]["content"])
        assert quote["address"] == "Example Street 1, Testville" and quote["delivery_fee"] == 1.99
        assert set(state.sessions) == {agent.session_id}
        await agent.send("Yes, confirm.")
    [order] = state.orders.values()
    assert order.session_id == agent.session_id
    assert order.cart.delivery_address == "Example Street 1, Testville"


@pytest.mark.parametrize("allowed_tools", [None, {"browse_menu"}])
async def test_unavailable_tools_cannot_be_dispatched(allowed_tools):
    model = ScriptedModel(
        [
            Reply(
                tool_calls=[
                    ToolCall("1", "get_operator_snapshot", {}),
                    ToolCall("3", "pizza_operator", {}),
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
        assert not names & {"pizza_operator", "get_operator_snapshot"}
        if allowed_tools is not None:
            assert names == allowed_tools
        turn = await agent.send("Read the operator view and confirm.")
    assert len(turn.calls) == 3 and all("rejected" in name for name in turn.calls)
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
                    ToolCall("1", "add_extra", {"item_id": "coke", "quantity": "2"}),
                    ToolCall("2", "set_delivery_address", {"address": 1012}),
                ]
            ),
            Reply("Two cokes. What is the street and house number?"),
        ]
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT)
        await agent.prepare()
        turn = await agent.send("Two cokes to 1012")
    history = model.requests[1][0]
    first, second = (json.loads(call["function"]["arguments"]) for call in history[2]["tool_calls"])
    # quantity declares an integer and address declares a string; the host repairs both.
    assert first == {"item_id": "coke", "quantity": 2}
    assert second == {"address": "1012"}
    assert turn.calls == ["add_extra", "set_delivery_address"]
    assert turn.coercions == 2


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
    assert turn.exhausted and turn.fallback and "Completed actions: add_extra" in turn.text
    assert fragments == [turn.text] and agent.messages[-1]["role"] == "tool"
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


async def test_silent_reply_is_asked_again_with_a_cue_that_stays_out_of_the_history():
    model = ScriptedModel(
        [
            Reply(tool_calls=[ToolCall("1", "add_extra", {"item_id": "coke"})]),
            Reply(None),  # the silent turn: no tool request and no text
            Reply("I added one Coke."),
        ]
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT)
        await agent.prepare()
        turn = await agent.send("One coke.")
    assert turn.text == "I added one Coke." and turn.reasks == 1 and not turn.fallback
    # Only the second request, the one after the silence, carries the cue.
    assert [CUE in messages for messages, _ in model.requests] == [False, False, True]
    assert CUE not in agent.messages and agent.messages[-1]["content"] == turn.text


async def test_fallback_goes_to_the_customer_and_not_into_the_history():
    model = ScriptedModel(
        [
            Reply(tool_calls=[ToolCall("1", "add_extra", {"item_id": "coke"})]),
            Reply(None),
            Reply(""),  # silent again after the cue
            Reply("You have one Coke."),
        ]
    )
    fragments = []
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT)
        await agent.prepare()
        turn = await agent.send("One coke.", on_text=fragments.append)
        assert turn.fallback and "Completed actions: add_extra" in turn.text
        assert fragments == [turn.text]
        # The model's next request must not hold the host's words as its own.
        await agent.send("What is in my cart?")
    assert not any("returned no answer" in str(m["content"]) for m in model.requests[-1][0])


async def test_failed_model_request_stays_out_of_the_history():
    class FailingModel:
        async def complete(self, messages, tools, *, on_text=None):
            raise ModelError("The model server did not answer.")

    async with Client(server.mcp) as client:
        agent = Agent(client, FailingModel(), PROMPT)
        await agent.prepare()
        turn = await agent.send("One coke.")
    assert turn.fallback and turn.error and "did not answer" in turn.text
    assert [m["role"] for m in agent.messages] == ["system", "user"]


async def test_silence_in_the_middle_of_a_task_can_continue_with_a_tool():
    model = ScriptedModel(
        [
            Reply(tool_calls=[ToolCall("1", "browse_menu", {"category": "drink"})]),
            Reply(None),  # silent in the middle of the task: nothing is added yet
            Reply(tool_calls=[ToolCall("2", "add_extra", {"item_id": "coke"})]),
            Reply("I added one Coke."),
        ]
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT)
        await agent.prepare()
        turn = await agent.send("One coke.")
    assert turn.calls == ["browse_menu", "add_extra"] and turn.reasks == 1
    reask, _ = model.requests[2]
    assert reask[-1] == CUE and CUE not in agent.messages

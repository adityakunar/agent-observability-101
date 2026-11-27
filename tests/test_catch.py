"""The host's claim check (catch.py): an answer that reports an action, with no change in the
record, gets one more step; if the claim stays, the customer reads a note.

A scripted model makes each claim on purpose, so the tests need no model server:

    uv run pytest tests/test_catch.py -v
"""

import copy

from fastmcp import Client

from agent_observability.catch import CORRECTION, NOTE, claims
from agent_observability.chat import PROMPT
from agent_observability.client import Agent
from agent_observability.model import Reply, ToolCall
from agent_observability.pizza import server, state
from agent_observability.pizza.operator.snapshot import get_operator_snapshot
from agent_observability.record import Recorder, load

BBQ = {"pizza_id": "bbq_chicken", "size": "personal", "crust": "thin"}
MARGHERITA = {"pizza_id": "margherita", "size": "personal", "crust": "thin"}
CLAIM = "I have removed the BBQ Chicken and added a personal Margherita."


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    async def complete(self, messages, tools, *, on_text=None):
        self.requests.append(copy.deepcopy(messages))
        return next(self.replies)


async def snapshot():
    return get_operator_snapshot()


def setup_function():
    state.sessions.clear()
    state.orders.clear()


async def swap_chat(path, replies, catch=True):
    """Order a BBQ Chicken, then ask for the swap. Return the agent, the model and the turn."""
    model = ScriptedModel(
        [Reply(tool_calls=[ToolCall("1", "customize_and_add", BBQ)]), Reply("Added.")] + replies
    )
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT, recorder=Recorder(path, snapshot), catch_claims=catch)
        await agent.prepare()
        await agent.send("A personal BBQ Chicken, thin crust.")
        turn = await agent.send("Swap it for a personal Margherita.")
    return agent, model, turn


async def test_a_caught_claim_gets_one_more_step_and_the_model_acts(tmp_path):
    agent, model, turn = await swap_chat(
        tmp_path / "chat.jsonl",
        [
            Reply(CLAIM),  # the claim: no tool ran
            Reply(tool_calls=[ToolCall("2", "customize_and_add", MARGHERITA)]),
            Reply(CLAIM),  # the record changed: the host lets the answer stand
        ],
    )
    assert turn.caught and not turn.warned
    assert turn.text == CLAIM and NOTE not in turn.text
    # Only the request right after the claim carries it and the correction.
    assert [CORRECTION in r for r in model.requests[2:]] == [False, True, False]
    # The history keeps neither the false claim nor the correction.
    assert CORRECTION not in agent.messages
    assert [m.get("content") for m in agent.messages].count(CLAIM) == 1
    steps = load(tmp_path / "chat.jsonl")[1]
    assert "1 × Margherita, Personal · Thin crust" in steps[-1]["record"]["after"]["cart"]
    assert [a["decision"] for s in steps for a in s["host"] if "tool" not in a] == ["caught claim"]


async def test_a_claim_that_stays_reaches_the_customer_with_a_note(tmp_path):
    _, _, turn = await swap_chat(tmp_path / "chat.jsonl", [Reply(CLAIM), Reply(CLAIM)])
    assert turn.caught and turn.warned
    assert turn.text == CLAIM + NOTE


async def test_an_honest_answer_after_the_catch_has_no_note(tmp_path):
    honest = "Sorry, I did not change your cart. Shall I swap it now?"
    _, _, turn = await swap_chat(tmp_path / "chat.jsonl", [Reply(CLAIM), Reply(honest)])
    assert turn.caught and not turn.warned and turn.text == honest


async def test_with_the_check_off_the_claim_goes_out_unchanged(tmp_path):
    _, model, turn = await swap_chat(tmp_path / "chat.jsonl", [Reply(CLAIM)], catch=False)
    assert not turn.caught and turn.text == CLAIM
    assert not any(CORRECTION in r for r in model.requests)


async def test_without_a_record_the_host_cannot_catch():
    # No snapshot: the host does not know whether the record changed, so it believes nothing.
    model = ScriptedModel([Reply(CLAIM)])
    async with Client(server.mcp) as client:
        agent = Agent(client, model, PROMPT)
        await agent.prepare()
        turn = await agent.send("Swap it for a personal Margherita.")
    assert not turn.caught and turn.text == CLAIM


def test_the_words_point_at_a_sentence_they_cannot_judge_it():
    assert claims("Your pizza has been updated to a large.")
    assert not claims("Would you like me to swap it?")
    # A false alarm: a refusal with an action word. The extra step makes it cheap.
    assert claims("I cannot change the size once it has been added to the cart.")

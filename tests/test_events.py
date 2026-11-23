"""Business events: what changed in the record during a turn. No model needed:

uv run pytest tests/test_events.py -v
"""

from agent_observability.events import by_turn, diff

EMPTY = {"cart": [], "deal": "No deal applied", "address": "No delivery address yet", "orders": []}
PIZZA = "1 × Pepperoni, Large · Thin crust"


def record(**fields):
    return {**EMPTY, **fields}


def step(turn, before, after):
    return {"turn": turn, "step": 1, "record": {"before": before, "after": after}}


def test_events_name_each_change_and_ignore_the_rest():
    before = record(cart=[PIZZA, "1 × Coke"])
    after = record(cart=[PIZZA, "1 × Coke", "1 × Coke"], address="Example Street 1", orders=["A1"])
    assert diff(before, after) == ["added 1 × Coke", "address Example Street 1", "order placed"]
    assert diff(after, after) == []


def test_a_turn_is_measured_from_its_first_step_to_its_last():
    middle = record(cart=[PIZZA])
    steps = [step(1, EMPTY, middle), step(1, middle, record()), step(2, record(), record())]
    # Added and removed again in one turn: no event, the customer has nothing.
    assert by_turn(steps) == {1: [], 2: []}

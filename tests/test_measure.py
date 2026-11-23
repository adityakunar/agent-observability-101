"""The count of done turns in the scripted chats of make measure. No model needed:

uv run pytest tests/test_measure.py -v
"""

from agent_observability.measure import ADDRESS, SCENARIOS, outcomes

ORDER = SCENARIOS["order"]

EMPTY = {"cart": [], "deal": "No deal applied", "address": "No delivery address yet", "orders": []}
PIZZA = "1 × Pepperoni, Large · Thin crust"
FULL = [PIZZA, "1 × Garlic Bread", "1 × Coke"]


def record(**fields):
    return {**EMPTY, **fields}


def step(turn, before, after):
    return {"turn": turn, "step": 1, "record": {"before": before, "after": after}}


def test_a_turn_counts_only_when_its_action_was_possible():
    with_pizza, done = record(cart=[PIZZA]), record(cart=FULL)
    saved = record(cart=FULL, address=ADDRESS)
    steps = [
        step(1, EMPTY, with_pizza),  # done
        step(2, with_pizza, record(cart=[PIZZA, "1 × Garlic Bread"])),  # half: missed
        step(3, record(cart=[PIZZA, "1 × Garlic Bread"]), with_pizza),  # no side and drink
        step(4, done, done),  # the address was possible and not saved
        step(5, saved, record(cart=FULL, address=ADDRESS, orders=["A1"])),  # done
    ]
    assert outcomes(steps, ORDER) == ["done", "missed", "not possible", "missed", "done"]


def test_an_order_without_approval_breaks_the_address_rule():
    saved = record(cart=FULL, address=ADDRESS)
    steps = [step(t, EMPTY, EMPTY) for t in (1, 2, 3)]
    steps += [step(4, record(cart=FULL), record(cart=FULL, address=ADDRESS, orders=["A1"]))]
    steps += [step(5, saved, saved)]
    assert outcomes(steps, ORDER)[3] == "missed"  # the address was saved, and the order too


def test_placing_the_order_needs_the_address_and_a_turn_that_ran():
    steps = [step(t, EMPTY, EMPTY) for t in (1, 2, 3, 4)]
    steps += [step(5, record(cart=FULL), record(cart=FULL))]  # no address: not possible
    assert outcomes(steps, ORDER)[4] == "not possible"
    # A record that ends early: the turns that never ran are not counted.
    assert outcomes(steps[:2], ORDER) == ["missed"] + ["not possible"] * 4

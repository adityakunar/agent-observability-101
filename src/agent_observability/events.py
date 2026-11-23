"""Turn the record of a chat (record.py) into business events, one list for each turn.

An event is a change in the business record between the start and the end of a turn:

    added 1 × Pepperoni, Large · Thin crust
    removed 1 × Coke
    deal Standard Meal Deal
    address Example Street 1, 1000 AB Testville
    order placed

The words of the model play no part. Code can count events in many chats; it cannot
count sentences.
"""

from collections import Counter
from typing import Any

from agent_observability.record import Step


def diff(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """The business events between two business records."""
    # Cart lines are a multiset: two identical lines are two items.
    old, new = Counter(before["cart"]), Counter(after["cart"])
    events = [f"added {line}" for line in (new - old).elements()]
    events += [f"removed {line}" for line in (old - new).elements()]
    if after["deal"] != before["deal"]:
        events.append(f"deal {after['deal']}")
    if after["address"] != before["address"]:
        events.append(f"address {after['address']}")
    events += ["order placed" for order in after["orders"] if order not in before["orders"]]
    return events


def by_turn(steps: list[Step]) -> dict[int, list[str]]:
    """The events of each turn: the record before its first step against after its last."""
    turns: dict[int, list[Step]] = {}
    for step in steps:
        turns.setdefault(step["turn"], []).append(step)
    return {
        turn: diff(of_turn[0]["record"]["before"], of_turn[-1]["record"]["after"])
        for turn, of_turn in turns.items()
    }

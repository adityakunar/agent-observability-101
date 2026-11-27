"""Measure how often the agent does what the customer asks.

    python -m agent_observability.measure run [SCENARIO] [CHATS] [CATCH] [TEMPERATURE]
        3 batches of CHATS chats (10); CATCH on (default) or off: the host's claim check
    python -m agent_observability.measure read [DIR]    count again from the records in DIR

Each chat of a scenario sends the same customer messages. Each one comes with an expectation: a
business rule written as a check on the events of its turn (events.py). A turn counts only
when its action was possible: the meal deal needs a pizza, a side and a drink in the cart.
The turns that were possible and missed are listed, for a person to read, with the
claims that the host caught (catch.py).
"""

import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastmcp import Client

from agent_observability.catch import claims
from agent_observability.client import Agent
from agent_observability.config import describe_model, llm_api_key, settings
from agent_observability.events import by_turn
from agent_observability.model import APIModel
from agent_observability.pizza import server
from agent_observability.pizza.operator.snapshot import get_operator_snapshot
from agent_observability.pizza.prompt import PROMPT
from agent_observability.pizza.state import DELIVERY_FEE
from agent_observability.record import Recorder, Step, load

RUNS = Path(".run/measure")
BATCHES = 3


@dataclass(frozen=True)
class Expectation:
    """A business rule as a check: when the customer says this, and the record allows it,
    the record shows these events at the end of the turn."""

    says: str
    then: tuple[str, ...]  # the start of each event that the turn must make
    never: tuple[str, ...] = ()  # the start of each event that the turn must not make
    cart: tuple[str, ...] = ()  # items that must be in the cart when the turn starts
    address: str = ""  # an address that must be saved when the turn starts
    total: bool = False  # the reply must quote the record's total with the delivery fee


ADDRESS = "Example Street 1, 1000 AB Testville"  # made up
MEAL = ("Pepperoni", "Garlic Bread", "Coke")  # a pizza, a side and a drink
# One scenario is one customer: the same messages in every chat, each with its rule.
SCENARIOS = {
    "order": (
        Expectation(
            "A large Pepperoni with thin crust, please.",
            then=("added 1 × Pepperoni, Large · Thin crust",),
        ),
        Expectation(
            "Add a garlic bread and a Coke.",
            then=("added 1 × Garlic Bread", "added 1 × Coke"),
            cart=("Pepperoni",),
        ),
        Expectation("Apply the meal deal.", then=("deal Standard Meal Deal",), cart=MEAL),
        # An address is not approval: the order waits for the customer's yes.
        Expectation(
            f"Deliver it to {ADDRESS}.", then=(f"address {ADDRESS}",), never=("order placed",)
        ),
        Expectation(
            "Yes, that's all correct. Place the order.",
            then=("order placed",),
            cart=MEAL,
            address=ADDRESS,
        ),
    ),
    # Chapter 2: an allergen question and an action in one message.
    "allergen": (
        Expectation(
            "Hi, I'll take a personal BBQ Chicken with thin crust",
            then=("added 1 × BBQ Chicken, Personal · Thin crust",),
        ),
        Expectation(
            "I'm allergic to celery. Is there celery in the BBQ sauce? If so, swap it for a"
            " personal Margherita, thin crust.",
            then=(
                "added 1 × Margherita, Personal · Thin crust",
                "removed 1 × BBQ Chicken, Personal · Thin crust",
            ),
            cart=("BBQ Chicken",),
        ),
    ),
    # A price promise: the reply quotes what the customer will pay.
    "total": (
        Expectation(
            "A large Pepperoni with thin crust, a garlic bread and a Coke, please.",
            then=(
                "added 1 × Pepperoni, Large · Thin crust",
                "added 1 × Garlic Bread",
                "added 1 × Coke",
            ),
        ),
        Expectation(
            f"Deliver it to {ADDRESS}. What will I pay in total, delivery included?",
            then=(f"address {ADDRESS}",),
            never=("order placed",),
            cart=MEAL,
            total=True,
        ),
    ),
    # A customer who changes their mind: a resize is one change_pizza call; without that
    # tool it takes two.
    "change": (
        Expectation(
            "A medium Veggie Supreme with original crust and a Coke, please.",
            then=("added 1 × Veggie Supreme, Medium · Original crust", "added 1 × Coke"),
        ),
        Expectation(
            "Actually, make the pizza a large.",
            then=(
                "added 1 × Veggie Supreme, Large · Original crust",
                "removed 1 × Veggie Supreme, Medium · Original crust",
            ),
            cart=("Veggie Supreme",),
        ),
        Expectation("And remove the Coke, please.", then=("removed 1 × Coke",), cart=("Coke",)),
    ),
}


def possible(expectation: Expectation, before: dict[str, Any]) -> bool:
    """Whether the record at the start of the turn allows the action."""
    # "2 × Pepperoni, Large · Thin crust" holds the item "Pepperoni".
    items = {line.split(" × ", 1)[-1].split(",")[0] for line in before["cart"]}
    has_address = not expectation.address or before["address"] == expectation.address
    return set(expectation.cart) <= items and has_address


def made(events: list[str], expected: str) -> bool:
    return any(event.startswith(expected) for event in events)


def quotes_total(steps: list[Step], turn: int) -> bool:
    """Whether the last reply of the turn holds the total with delivery, as 22.96."""
    last = [step for step in steps if step["turn"] == turn][-1]
    total = float(last["record"]["after"]["total"].lstrip("€")) + DELIVERY_FEE
    return f"{total:.2f}" in (last["model"]["text"] or "")


def outcomes(steps: list[Step], scenario: tuple[Expectation, ...]) -> list[str]:
    """For each expectation: 'done', 'missed' (possible, not done) or 'not possible'."""
    events = by_turn(steps)
    result = []
    for turn, expectation in enumerate(scenario, start=1):
        first = [step for step in steps if step["turn"] == turn][:1]
        if not first or not possible(expectation, first[0]["record"]["before"]):
            result.append("not possible")  # also a turn that the record does not reach
        elif (
            all(made(events[turn], e) for e in expectation.then)
            and not any(made(events[turn], e) for e in expectation.never)
            and (not expectation.total or quotes_total(steps, turn))
        ):
            result.append("done")
        else:
            result.append("missed")
    return result


def false_claims(steps: list[Step]) -> tuple[int, int, int]:
    """Count the turns of one chat: claims caught, claims warned, and claims that reached the
    customer with no note. A claim: the answer has an action word, and the record of the
    whole turn did not change. With the check off, every claim reaches the customer."""
    caught = warned = unseen = 0
    for turn in sorted({step["turn"] for step in steps}):
        of_turn = [step for step in steps if step["turn"] == turn]
        decisions = {act["decision"] for step in of_turn for act in step["host"]}
        caught += "caught claim" in decisions
        warned += "warned" in decisions
        last = of_turn[-1]
        unchanged = of_turn[0]["record"]["before"] == last["record"]["after"]
        if unchanged and claims(last["model"]["text"] or "") and "warned" not in decisions:
            unseen += 1
    return caught, warned, unseen


async def record(
    folder: Path, name: str, chats: int, catch: bool, temperature: float | None
) -> None:
    """Record the chats with the configured model. The tools run in this process."""
    model = APIModel(
        settings.llm_base_url,
        settings.llm_model,
        api_key=llm_api_key(),
        temperature=temperature,
    )

    async def snapshot() -> dict:  # type: ignore[type-arg]
        return get_operator_snapshot()

    conditions = {
        "model": describe_model(),
        "temperature": temperature,
        "catch": catch,
        "scenario": name,
        "script": [e.says for e in SCENARIOS[name]],
    }
    folder.mkdir(parents=True)
    (folder / "conditions.json").write_text(json.dumps(conditions, indent=1))
    # A tool that refuses (a deal without a side) answers the model, as in make chat. The
    # record keeps it; the traceback that FastMCP also logs would bury the count.
    logging.getLogger("fastmcp").setLevel(logging.CRITICAL)
    try:
        for batch in range(1, BATCHES + 1):
            for chat in range(1, chats + 1):
                path = folder / f"batch{batch}" / f"chat{chat:02d}.jsonl"
                async with Client(server.mcp) as client:
                    agent = Agent(
                        client,
                        model,
                        PROMPT,
                        recorder=Recorder(path, snapshot),
                        catch_claims=catch,
                    )
                    await agent.prepare()
                    for expectation in SCENARIOS[name]:
                        await agent.send(expectation.says)
                done = outcomes(load(path)[1], SCENARIOS[name])
                print(f"batch {batch} chat {chat:2d}  {' '.join(done)}")
    finally:
        await model.client.close()


def report(folder: Path) -> None:
    """Count done turns out of possible turns, per batch, and list the misses."""
    path = folder / "conditions.json"
    conditions = json.loads(path.read_text()) if path.exists() else {}
    if conditions:  # the number means little without them
        catch = "on" if conditions.get("catch", False) else "off"  # off: runs before Chapter 4
        print(
            f"{conditions['model']}, temperature {conditions['temperature']}, claim check {catch}"
        )
    scenario = SCENARIOS[conditions.get("scenario", "order")]
    batches = sorted(folder.glob("batch*"))
    table = [[[0, 0] for _ in batches] for _ in scenario]  # [done, possible]
    missed = []
    claimed = [[0, 0, 0] for _ in batches]  # [caught, warned, unseen] for each batch
    for b, batch in enumerate(batches):
        for chat in sorted(batch.glob("chat*.jsonl")):
            steps = load(chat)[1]
            claimed[b] = [a + n for a, n in zip(claimed[b], false_claims(steps), strict=True)]
            for t, outcome in enumerate(outcomes(steps, scenario)):
                if outcome == "not possible":
                    continue
                table[t][b][1] += 1
                if outcome == "done":
                    table[t][b][0] += 1
                    continue
                reply = [s for s in steps if s["turn"] == t + 1][-1]["model"]["text"] or ""
                missed.append(f"{batch.name} {chat.stem} turn {t + 1}  {' '.join(reply.split())}")
    print(f"records: {folder}\ndone of possible")
    print("turn  " + "".join(f"{b.name:>9}" for b in batches) + "    total")
    for t, row in enumerate(table):
        done, possible = sum(c[0] for c in row), sum(c[1] for c in row)
        cells = "".join(f"{f'{c[0]}/{c[1]}':>9}" for c in row)
        print(f"{t + 1:>4}  {cells}  {done:>3}/{possible:<3} {scenario[t].says}")
    print("\nclaims with no change in the record, all turns")
    for i, label in enumerate(("caught", "warned", "unseen")):
        cells = "".join(f"{c[i]:>9}" for c in claimed)
        print(f"{label:>6}{cells}  {sum(c[i] for c in claimed):>5}")
    print("caught: the host asked again; warned: the customer read a note;")
    print("unseen: the customer read the claim with no note. The words only point at a sentence.")
    print(
        f"\nMissed: {len(missed)} turns where the action was possible and the record does not show it."
    )
    print("Read them: the record shows what did not happen, the reply shows why.")
    print("\n".join(missed))


def main() -> None:
    verb = sys.argv[1] if len(sys.argv) > 1 else "read"
    if verb == "run":
        name = sys.argv[2] if len(sys.argv) > 2 else "order"
        if name not in SCENARIOS:
            raise SystemExit(f"Unknown scenario {name!r}. Choose one of: {', '.join(SCENARIOS)}.")
        folder = RUNS / f"{datetime.now():%Y%m%d-%H%M%S}-{name}"
        chats = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        catch = sys.argv[4] if len(sys.argv) > 4 else "on"
        if catch not in ("on", "off"):
            raise SystemExit(f"CATCH is on or off, not {catch!r}.")
        # A temperature here replaces the one of the profile, for this run only.
        temperature = float(sys.argv[5]) if len(sys.argv) > 5 else settings.llm_temperature
        asyncio.run(record(folder, name, chats, catch == "on", temperature))
    elif verb == "read":
        runs = sorted(RUNS.glob("*/"))
        if len(sys.argv) > 2:
            folder = Path(sys.argv[2])
        elif runs:
            folder = runs[-1]
        else:
            raise SystemExit(f"No run in {RUNS}/. Run make measure first.")
    else:
        raise SystemExit(__doc__)
    report(folder)


if __name__ == "__main__":
    main()

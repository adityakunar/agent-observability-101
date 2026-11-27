"""Record each model request of a chat as one JSON line with three layers.

model   what the model returned: its text and the tool calls it asked for
host    what the host did with each call: ran it, rejected it, or blocked a repeat
record  the customer's cart and orders, before and after the step

A layer alone says little. A fault is where two layers disagree, and
inspector.py finds that place.
"""

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from agent_observability.llm.contracts import Reply
from agent_observability.pizza.domain import Cart
from agent_observability.pizza.operator.tickets import cart_ticket

# One step: one model request and everything that followed from it.
Step = dict[str, Any]
# Returns the delivery desk's snapshot: /desk/snapshot in the chat, the function in a test.
Snapshot = Callable[[], Awaitable[dict[str, Any]]]


def business_record(snapshot: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Reduce the desk's snapshot to one customer: the cart and the placed orders."""
    carts = [c for c in snapshot["active_carts"] if c["session_id"] == session_id]
    # A customer with no cart yet has the same record as one with an empty cart.
    cart = carts[0] if carts else cart_ticket(session_id, Cart(session_id=session_id))
    return {
        # "1 × BBQ Chicken, Personal · Thin crust"; a drink or a side has no variant.
        "cart": [", ".join(filter(None, (ln["title"], ln["variant"]))) for ln in cart["lines"]],
        "deal": cart["deal"],
        "address": cart["address"],
        "total": cart["total"],
        "orders": [o["order_id"] for o in snapshot["orders"] if o["session_id"] == session_id],
    }


def load(path: Path) -> tuple[dict[str, Any], list[Step]]:
    """Return the session line and the step lines of one record."""
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    return lines[0], lines[1:]


class Recorder:
    """Write the steps of one chat to a file. With no path, it records nothing."""

    def __init__(self, path: Path | None = None, snapshot: Snapshot | None = None) -> None:
        self.path = path
        self.snapshot = snapshot
        self.session_id = ""
        self.customer = ""  # the customer message of the current turn
        self.turn = 0
        self.step = 0
        self.state: dict[str, Any] = {}  # the business record after the last step
        self.turn_start: dict[str, Any] = {}  # the business record when the turn began

    def start(self, session_id: str, **facts: Any) -> None:
        """Write the first line: the facts that hold for the whole chat."""
        self.session_id = session_id
        self._write({"kind": "session", "session_id": session_id, **facts})

    async def begin_turn(self, customer: str) -> None:
        self.customer = customer
        self.turn += 1
        self.step = 0
        self.state = self.turn_start = await self._read_record()

    def unchanged_turn(self) -> bool:
        """Whether the business record is the same as at the start of the turn.

        False when there is no record to read: with no snapshot, nothing is known.
        """
        return self.snapshot is not None and self.state == self.turn_start

    def begin_step(
        self, request: list[dict[str, Any]] | None, reply: Reply | None, with_tools: bool = True
    ) -> Step:
        """Start the entry for one model request. The host adds its decisions to "host"."""
        self.step += 1
        return {
            "kind": "step",
            "turn": self.turn,
            "step": self.step,
            "customer": self.customer,
            # The exact messages of this request, not the history: the host sometimes
            # sends words that it keeps out of the history (the cue, the wrap-up).
            # A copy: the host's list grows with each step, and a record must not.
            "request": list(request) if request else None,
            "with_tools": with_tools,  # the wrap-up request carries no tool definitions
            "context_tokens": reply.context_tokens if reply else None,
            "model": {
                "text": reply.text if reply else None,
                # The arguments as they arrived, before the host repaired them.
                "calls": [
                    {"tool": call.name, "arguments": call.arguments}
                    for call in (reply.tool_calls if reply else [])
                ],
            },
            "host": [],
        }

    async def end_step(self, step: Step) -> None:
        """Read the business record again and write the entry."""
        before, self.state = self.state, await self._read_record()
        step["record"] = {"before": before, "after": self.state}
        self._write(step)

    async def _read_record(self) -> dict[str, Any]:
        if self.snapshot is None:
            return {}
        return business_record(await self.snapshot(), self.session_id)

    def _write(self, line: dict[str, Any]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as file:
            file.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")

"""The host: discover the server's tools, own the session and run one customer turn.

Read this file from top to bottom:

1. Turn            the result of one customer message
2. Agent.prepare   read the tool catalog from the MCP server
3. Agent.send      the bounded model → tools → model loop
4. the helpers     record the model's reply, run its tool requests, call one tool

The model proposes. The host executes. The recorder (record.py) writes down both,
and what changed in the business record.
"""

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_observability.catch import CORRECTION, NOTE, false_claim
from agent_observability.events import diff
from agent_observability.model import Model, ModelError, Reply, TextCallback, ToolCall
from agent_observability.record import Recorder, Step

# What the host adds when it asks a silent model again: a message with no words. It
# closes the turn that the model left open and starts a new one. Words here are an
# instruction, and a small model follows an instruction literally: "reply" made it
# describe actions that it did not take, and "continue" made it place an order.
CUE = {"role": "user", "content": ""}


@dataclass
class Turn:
    """The result of one customer message."""

    text: str  # the answer that the customer sees
    # Tool names in the order of the calls. A suffix in brackets marks a call that did
    # not run: "(rejected)" or "(duplicate suppressed)".
    calls: list[str] = field(default_factory=list)
    coercions: int = 0  # arguments whose type the host repaired
    exhausted: bool = False  # the step budget or the tool-call budget stopped the turn
    duplicates: int = 0  # repeated business actions that the host did not run again
    reasks: int = 0  # silent replies that the host asked again, with a cue to speak
    fallback: bool = False  # the host wrote the answer, because the model gave none
    caught: bool = False  # the host caught a claim that the record does not back (catch.py)
    warned: bool = False  # the claim stayed after the correction; the customer reads a note
    error: str | None = None  # the error text, if a model request failed


class Agent:
    def __init__(
        self,
        client: Client[Any],
        model: Model,
        prompt: str,
        *,
        allowed_tools: set[str] | None = None,
        max_tool_iterations: int = 12,
        max_tool_calls: int = 16,
        recorder: Recorder | None = None,
        catch_claims: bool = True,
    ) -> None:
        if max_tool_iterations < 1 or max_tool_calls < 1:
            raise ValueError("Model-step and tool-call budgets must be positive.")
        self.client = client
        self.model = model
        self.session_id = uuid4().hex  # one cart for each chat; the host adds it to tool calls
        self.recorder = recorder or Recorder()  # with no path, it records nothing
        self.allowed_tools = allowed_tools
        self.max_tool_iterations = max_tool_iterations  # model requests for each customer message
        self.max_tool_calls = max_tool_calls  # tool calls for each customer message
        self.catch_claims = catch_claims  # check each answer against the record (catch.py)
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
        self.tools: list[dict[str, Any]] = []  # the catalog in the shape of the model API
        self.available: dict[str, dict[str, Any]] = {}  # the same catalog, by tool name
        self.session_tools: set[str] = set()  # tools that need the session ID
        self.mutation_tools: set[str] = set()  # tools that can change business records

    async def prepare(self) -> None:
        """Read the server's tool list and build the catalog that the model sees."""
        self.available.clear()
        self.session_tools.clear()
        self.mutation_tools.clear()
        for tool in await self.client.list_tools():
            if self.allowed_tools is not None and tool.name not in self.allowed_tools:
                continue  # the caller limited this agent to a subset of the tools
            schema = copy.deepcopy(tool.input_schema)
            # The host owns the session ID. Remove the parameter from the schema, so the
            # model cannot select the cart of a different chat.
            if "session_id" in schema.get("properties", {}):
                self.session_tools.add(tool.name)
                schema["properties"].pop("session_id")
                schema["required"] = [k for k in schema.get("required", []) if k != "session_id"]
            # A tool without the read-only hint can change business records.
            if not (tool.annotations and tool.annotations.read_only_hint):
                self.mutation_tools.add(tool.name)
            self.available[tool.name] = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": schema,
                },
            }
        self.tools = list(self.available.values())
        self.recorder.start(
            self.session_id, tools=self.tools, business_tools=sorted(self.mutation_tools)
        )

    async def send(
        self,
        text: str,
        *,
        on_text: TextCallback | None = None,
        on_tool: Callable[[str], None] | None = None,
        on_host: Callable[[str], None] | None = None,
    ) -> Turn:
        """Run one customer message: ask the model, run its tool requests, ask again."""
        self.messages.append({"role": "user", "content": text})
        turn = Turn("")
        completed: dict[str, str] = {}  # business actions done in this turn, with their results
        dispatched = 0  # tool calls made in this turn
        extra: list[dict[str, Any]] = []  # host messages for the next request only
        await self.recorder.begin_turn(text)
        try:
            for _ in range(self.max_tool_iterations):
                advertised = {tool["function"]["name"] for tool in self.tools}
                # After a silent reply, the next request carries the cue; after a caught
                # claim, the claim and the correction. They go on a copy, so they do not
                # stay in the conversation.
                request, extra = [*self.messages, *extra], []
                reply = await self.model.complete(request, self.tools, on_text=self._live(on_text))
                step = self.recorder.begin_step(request, reply)
                text = reply.text or ""
                if not reply.tool_calls and not text.strip():
                    # The reply is silent: no tool request and no text. Some models end
                    # their turn like this after a tool result. Ask again, one time for
                    # each customer message; a second silence gets the host's answer.
                    if not turn.reasks:
                        turn.reasks += 1
                        extra = [CUE]
                        step["host"].append({"decision": "asked again"})
                        await self.recorder.end_step(step)
                        continue
                    # Still silent. The host answers. The history keeps only the
                    # model's own words.
                    turn.fallback = True
                    turn.text = self._fallback(turn.calls, "The model returned no answer.")
                    step["host"].append({"decision": "fallback", "result": turn.text})
                    await self.recorder.end_step(step)
                    if on_text:
                        on_text(turn.text)
                    return turn
                prepared = self._record_reply(reply, turn)
                if not prepared:
                    # No tool requests: the model's text is the answer, unless the host
                    # catches a claim that the record does not back (catch.py).
                    extra = await self._answer(text, turn, step, on_text, on_host)
                    if extra:
                        continue
                    await self.recorder.end_step(step)
                    return turn
                dispatched = await self._run_tools(
                    prepared, advertised, turn, completed, dispatched, on_tool, step
                )
                await self.recorder.end_step(step)
                # Stop when the tool-call budget is used, or when the model repeated a
                # business action. The wrap-up below gives the answer.
                if turn.exhausted or turn.duplicates:
                    break
            else:
                turn.exhausted = True  # all model steps used and still no text answer
            # Wrap-up: one more model request, with no tools. It uses a copy of the history,
            # so the added instruction does not stay in the conversation.
            wrapup = copy.deepcopy(self.messages)
            wrapup[0]["content"] += (
                "\nThis turn has stopped. Summarize only successful tool results and any rejections. "
                "Repeated business actions were suppressed. Ask one necessary next question. "
                "Do not claim unperformed actions or propose more tool calls this turn."
            )
            reply = await self.model.complete(wrapup, [], on_text=self._live(on_text))
            step = self.recorder.begin_step(wrapup, reply, with_tools=False)
            if reply.text and reply.text.strip():
                # The wrap-up has no tools, so a caught claim gets the note, not a retry.
                self.messages.append({"role": "assistant", "content": reply.text})
                await self._answer(reply.text, turn, step, on_text, on_host, retry=False)
                await self.recorder.end_step(step)
                return turn
            turn.text = self._fallback(
                turn.calls, "This turn stopped before the model could finish."
            )
            if on_text:
                on_text(turn.text)  # the fallback text was not streamed; show it now
        except ModelError as exc:
            # A model request failed. Tell the customer which actions were already done.
            turn.error = str(exc)
            turn.text = self._fallback(turn.calls, str(exc))
            step = self.recorder.begin_step(None, None)  # the request failed: no reply to record
            if on_text:
                on_text("\n" + turn.text)
        # The host wrote this answer. It goes to the customer, not into the history:
        # a model copies what it finds there.
        turn.fallback = True
        step["host"].append({"decision": "fallback", "result": turn.text})
        await self.recorder.end_step(step)
        return turn

    def _live(self, on_text: TextCallback | None) -> TextCallback | None:
        """The callback that streams the model's words: none while the check holds them."""
        return None if self._gated() else on_text

    def _gated(self) -> bool:
        """Whether the host checks each answer: the check is on and the record can be read."""
        return self.catch_claims and self.recorder.turn_records() is not None

    async def _answer(
        self,
        text: str,
        turn: Turn,
        step: Step,
        on_text: TextCallback | None,
        on_host: Callable[[str], None] | None,
        retry: bool = True,
    ) -> list[dict[str, Any]]:
        """Check an answer against the events of its turn (catch.py), then show it.

        The answer is the last message of the history. A first false claim of the turn,
        with a retry allowed: take it out of the history and return it with the
        correction, the messages of the retry. Otherwise a false claim gets the note, in
        the answer and in the history, so the next turn does not build on it. With the
        check on, the words reach the customer only here, after the check.
        """
        turn.text = text
        records = self.recorder.turn_records()
        if self.catch_claims and records and false_claim(text, diff(*records)):
            if retry and not turn.caught:
                turn.caught = True
                step["host"].append({"decision": "caught claim"})
                await self.recorder.end_step(step)
                if on_host:
                    on_host("the answer reports a change; the record has none. Asked again.")
                return [self.messages.pop(), CORRECTION]
            turn.warned = True
            turn.text = self.messages[-1]["content"] = text + NOTE
            step["host"].append({"decision": "warned", "result": NOTE.strip()})
        if self._gated() and on_text:
            on_text(turn.text)
        return []

    def _fallback(self, calls: list[str], reason: str) -> str:
        """The host's own answer when the model gives none. It lists only actions that ran."""
        # A name with a suffix, such as "apply_deal (rejected)", is a call that did not run.
        completed = [name for name in calls if " (" not in name and name in self.mutation_tools]
        return reason + (
            " Completed actions: "
            + ", ".join(completed)
            + ". Changes already made were kept; review the cart or orders before continuing."
            if completed
            else " No business changes were completed this turn."
        )

    def _record_reply(self, reply: Reply, turn: Turn) -> list[tuple[ToolCall, dict[str, Any]]]:
        """Add the model's reply to the history, in the shape that the model API expects.

        Return the tool requests, each with its repaired arguments.
        """
        prepared = []
        for call in reply.tool_calls:
            arguments, coerced = self._normalize_arguments(call.name, call.arguments)
            turn.coercions += len(coerced)
            prepared.append((call, arguments))
        message: dict[str, Any] = {"role": "assistant", "content": reply.text}
        if prepared:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(arguments)},
                }
                for call, arguments in prepared
            ]
        self.messages.append(message)
        return prepared

    def _normalize_arguments(
        self, name: str, arguments: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        """Repair simple type slips in replies that reached the host; MCP validates the rest."""
        schema = self.available.get(name, {}).get("function", {}).get("parameters", {})
        properties = schema.get("properties", {})
        normalized = dict(arguments)
        normalized.pop("session_id", None)  # the host adds the session ID in _dispatch
        for key, parameter in properties.items():
            if key not in normalized and "default" in parameter:
                normalized[key] = parameter["default"]
        coerced: list[str] = []
        for key, value in normalized.items():
            expected = properties.get(key, {}).get("type")
            # A number where the schema wants text, for example house number 12.
            # In Python, True and False are also integers; do not change them.
            if (
                expected == "string"
                and isinstance(value, (int, float))
                and (not isinstance(value, bool))
            ):
                normalized[key] = str(value)
                coerced.append(key)
            elif expected == "integer" and isinstance(value, str):
                # Text where the schema wants an integer, for example quantity "2".
                try:
                    normalized[key] = int(value)
                except ValueError:
                    continue  # not a number; the server rejects it with a clear message
                coerced.append(key)
        return (normalized, coerced)

    async def _run_tools(
        self,
        prepared: list[tuple[ToolCall, dict[str, Any]]],
        advertised: set[str],
        turn: Turn,
        completed: dict[str, str],
        dispatched: int,
        on_tool: Callable[[str], None] | None,
        step: Step,
    ) -> int:
        """Run the tool requests of one reply. Return the new count of tool calls.

        Each request gets one tool message, also a request that the host refuses.
        The model API needs an answer for each call ID, and the model can read the
        refusal and correct itself.
        """
        for call, arguments in prepared:
            if on_tool:
                on_tool(call.name)
            # The same tool with the same arguments is the same action.
            fingerprint = json.dumps([call.name, arguments], sort_keys=True)
            decision = "ran"
            try:
                if call.name not in advertised:
                    raise ToolError(f"Tool {call.name!r} is not available to this agent.")
                if dispatched >= self.max_tool_calls:
                    turn.exhausted = True
                    raise ToolError(
                        "Tool-call budget reached; no further tools will execute this turn."
                    )
                dispatched += 1
                if call.name in self.mutation_tools and fingerprint in completed:
                    # The model asked for the same business action twice in one turn.
                    # Do not run it again; give the first result back.
                    turn.duplicates += 1
                    decision = "blocked repeat"
                    output = (
                        "Already completed once this turn; not executed again. Use quantity for identical items. Previous result: "
                        + completed[fingerprint]
                    )
                    turn.calls.append(f"{call.name} (duplicate suppressed)")
                else:
                    data = await self._dispatch(call.name, arguments, turn.calls)
                    output = json.dumps(data, ensure_ascii=False, default=str)
                    if call.name in self.mutation_tools:
                        completed[fingerprint] = output
            except ToolError as exc:
                decision = "rejected"
                output = f"Rejected: {exc}"
                turn.calls.append(f"{call.name} (rejected)")
            step["host"].append(
                {"tool": call.name, "arguments": arguments, "decision": decision, "result": output}
            )
            self.messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
        return dispatched

    async def _dispatch(self, name: str, arguments: dict[str, Any], calls: list[str]) -> Any:
        """Call one tool on the MCP server, with the host's session ID."""
        if name in self.session_tools:
            arguments = {**arguments, "session_id": self.session_id}
        result = await self.client.call_tool(name, arguments)
        data = result.data
        calls.append(name)
        return data

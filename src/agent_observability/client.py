"""The host's public interface: discover tools, own a session, send one turn."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from fastmcp import Client

from agent_observability.host.catalog import normalize_arguments, prepare
from agent_observability.host.dispatch import dispatch
from agent_observability.host.loop import run_turn
from agent_observability.host.turn import Turn
from agent_observability.model import Model, TextCallback


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
        choose_address: Callable[[list[dict[str, str]]], Awaitable[str | None]] | None = None,
    ) -> None:
        if max_tool_iterations < 1 or max_tool_calls < 1:
            raise ValueError("Model-step and tool-call budgets must be positive.")
        self.client = client
        self.model = model
        self.session_id = uuid4().hex
        self.allowed_tools = allowed_tools
        self.max_tool_iterations = max_tool_iterations
        self.max_tool_calls = max_tool_calls
        self.choose_address = choose_address
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
        self.tools: list[dict[str, Any]] = []
        self.available: dict[str, dict[str, Any]] = {}
        self.session_tools: set[str] = set()
        self.mutation_tools: set[str] = set()

    async def prepare(self) -> None:
        await prepare(self)

    def _normalize_arguments(
        self, name: str, arguments: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str]]:
        return normalize_arguments(self, name, arguments)

    async def _dispatch(self, name: str, arguments: dict[str, Any], calls: list[str]) -> Any:
        return await dispatch(self, name, arguments, calls)

    async def send(
        self,
        text: str,
        *,
        on_text: TextCallback | None = None,
        on_tool: Callable[[str], None] | None = None,
    ) -> Turn:
        return await run_turn(self, text, on_text=on_text, on_tool=on_tool)

"""The host needs text and complete tool requests, independent of the provider."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

# Receives each streamed text fragment as it arrives; the terminal prints it.
TextCallback = Callable[[str], None]


# Plain dataclasses: the adapter builds these from already-parsed provider responses,
# so there is nothing left to validate. Pydantic stays at the boundaries (settings, tools).
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Reply:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ModelError(RuntimeError):
    """A failed request or incomplete reply; no pending calls may be dispatched."""


class Model(Protocol):
    """Anything with this method can drive the agent; no base class to inherit.

    A Protocol is checked by shape, so `APIModel`, a test's scripted model or your
    own client qualify without importing this module. Libraries such as LiteLLM
    put many providers behind a similar single call.
    """

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        on_text: TextCallback | None = None,
    ) -> Reply: ...

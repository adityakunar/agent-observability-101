"""Discover allowed tools and normalize the model's simple argument slips."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_observability.client import Agent


async def prepare(agent: Agent) -> None:
    agent.available.clear()
    agent.session_tools.clear()
    agent.mutation_tools.clear()
    for tool in await agent.client.list_tools():
        ui = (tool.meta or {}).get("ui", {})
        visibility = ui.get("visibility", ["model"])
        if (
            ui.get("resourceUri")
            or "model" not in visibility
            or (agent.allowed_tools is not None and tool.name not in agent.allowed_tools)
        ):
            continue
        schema = copy.deepcopy(tool.input_schema)
        if "session_id" in schema.get("properties", {}):
            agent.session_tools.add(tool.name)
            schema["properties"].pop("session_id")
            schema["required"] = [k for k in schema.get("required", []) if k != "session_id"]
        if not (tool.annotations and tool.annotations.read_only_hint):
            agent.mutation_tools.add(tool.name)
        agent.available[tool.name] = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": schema,
            },
        }
    agent.tools = list(agent.available.values())


def normalize_arguments(
    agent: Agent, name: str, arguments: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Repair simple type slips in replies that reached the host; MCP validates the rest."""
    schema = agent.available.get(name, {}).get("function", {}).get("parameters", {})
    properties = schema.get("properties", {})
    normalized = dict(arguments)
    normalized.pop("session_id", None)
    for key, parameter in properties.items():
        if key not in normalized and "default" in parameter:
            normalized[key] = parameter["default"]
    coerced: list[str] = []
    for key, value in normalized.items():
        expected = properties.get(key, {}).get("type")
        if (
            expected == "string"
            and isinstance(value, (int, float))
            and (not isinstance(value, bool))
        ):
            normalized[key] = str(value)
            coerced.append(key)
        elif expected == "integer" and isinstance(value, str):
            try:
                normalized[key] = int(value)
            except ValueError:
                continue
            coerced.append(key)
    return (normalized, coerced)

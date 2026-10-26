"""Dispatch tools with the host's session and the customer's direct address choice."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_observability.client import Agent


async def dispatch(agent: Agent, name: str, arguments: dict[str, Any], calls: list[str]) -> Any:
    if name in agent.session_tools:
        arguments = {**arguments, "session_id": agent.session_id}
    result = await agent.client.call_tool(name, arguments)
    data = result.data
    calls.append(name)
    if (
        name == "lookup_delivery_addresses"
        and data["candidates"]
        and (agent.choose_address is not None)
    ):
        chosen = await agent.choose_address(data["candidates"])
        data = {
            **data,
            "selected": None,
            "message": "The customer declined these candidates. Ask for corrected address details.",
        }
        if chosen is not None:
            selection = await agent.client.call_tool(
                "select_delivery_address", {"session_id": agent.session_id, "address_id": chosen}
            )
            data["selected"] = selection.data
            data["message"] = (
                "The customer selected and saved the address in selected. Review the cart and delivery quote, then ask for separate order approval. Do not ask the customer to choose the address again."
            )
            calls.append("select_delivery_address (customer)")
    return data

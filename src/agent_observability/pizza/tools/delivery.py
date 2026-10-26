"""Lantern Pizza delivery business actions."""

from typing import Any

from fastmcp import FastMCP
from pydantic import ValidationError

from agent_observability.pizza import state
from agent_observability.utilities import addresses as address_service

mcp = FastMCP("Lantern Pizza Delivery")


@mcp.tool()
async def lookup_delivery_addresses(
    session_id: str, street: str, house_number: str | int
) -> dict[str, Any]:
    """Look up real delivery addresses in Amsterdam's 1012 area. Provide the customer's street and house number. Similar street names may return suggestions. The customer must choose an address in the chat; the model cannot select one. A new lookup clears the previous choice."""
    cart = state.get_cart(session_id)
    cart.delivery_address = None
    cart.address_candidates.clear()
    try:
        candidates = await address_service.address_lookup.search(street, str(house_number))
    except (OSError, RuntimeError, ValidationError) as exc:
        raise ValueError("Address lookup is unavailable. Try again before confirming.") from exc
    cart.address_candidates = {a.id: a for a in candidates}
    return {
        "candidates": [{"id": a.id, "address": a.label} for a in candidates],
        "message": (
            "Ask the customer to choose their address."
            if candidates
            else "No matching address in our Amsterdam 1012 delivery area. Please check the street and house number."
        ),
    }


@mcp.tool(meta={"ui": {"visibility": ["app"]}})
def select_delivery_address(session_id: str, address_id: str) -> dict[str, Any]:
    """Save the customer's address choice. Host-only: unavailable to the model."""
    cart = state.get_cart(session_id)
    address = cart.address_candidates.get(address_id)
    if address is None:
        raise ValueError("Choose an address returned by the current lookup for this cart.")
    cart.delivery_address = address
    cart.address_candidates.clear()
    return get_delivery_estimate(session_id)


@mcp.tool(annotations={"readOnlyHint": True})
def get_delivery_estimate(session_id: str) -> dict[str, Any]:
    """Show the delivery fee/time for the address chosen by the customer. Use lookup_delivery_addresses first; a typed address or model assertion is not a selection."""
    cart = state.sessions.get(session_id)
    if cart is None or cart.delivery_address is None:
        raise ValueError("The customer must choose a delivery address first.")
    return {
        "delivery_fee": state.DELIVERY_FEE,
        "estimated_minutes": state.DELIVERY_MINUTES,
        "address": cart.delivery_address.label,
        "currency": state.CURRENCY,
    }

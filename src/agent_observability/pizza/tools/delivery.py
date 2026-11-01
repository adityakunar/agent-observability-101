"""Lantern Pizza delivery business actions."""

from typing import Any

from fastmcp import FastMCP

from agent_observability.pizza import state

mcp = FastMCP("Lantern Pizza Delivery")


@mcp.tool()
def set_delivery_address(session_id: str, address: str) -> dict[str, Any]:
    """Save the delivery address in the customer's own words: street, house number and city. Ask the customer first; never invent or complete an address. Returns the delivery fee and time."""
    address = " ".join(address.split())
    if not address:
        raise ValueError("The address is empty. Ask the customer for the delivery address.")
    state.get_cart(session_id).delivery_address = address
    return {
        "address": address,
        "delivery_fee": state.DELIVERY_FEE,
        "estimated_minutes": state.DELIVERY_MINUTES,
        "currency": state.CURRENCY,
    }

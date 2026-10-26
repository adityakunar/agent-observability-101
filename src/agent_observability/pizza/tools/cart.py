"""Lantern Pizza cart tools."""

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from agent_observability.pizza import state
from agent_observability.pizza.domain import Cart

mcp = FastMCP("Lantern Pizza Cart")


@mcp.tool(annotations={"readOnlyHint": True})
def view_cart(session_id: str) -> dict[str, Any]:
    """Return the cart, stable line_id values, quantities, applied deal and totals. Read before editing items."""
    cart = state.sessions.get(session_id) or Cart(session_id=session_id)
    return state.cart_to_dict(cart)


@mcp.tool()
def remove_cart_item(session_id: str, line_id: str) -> dict[str, Any]:
    """Remove the entire cart line selected by the customer. Use its line_id from view_cart; ask which variant if ambiguous."""
    cart = state.get_cart(session_id)
    item = next((item for item in cart.items if item.line_id == line_id), None)
    if item is None:
        raise ValueError("Unknown cart line. Use view_cart to find its line_id.")
    cart.items.remove(item)
    state.refresh_deal(cart)
    return state.cart_to_dict(cart)


@mcp.tool()
def set_cart_item_quantity(
    session_id: str, line_id: str, quantity: Annotated[int, Field(ge=1)]
) -> dict[str, Any]:
    """Set a cart line's total quantity to the customer's requested number. Use remove_cart_item to delete it."""
    cart = state.get_cart(session_id)
    item = next((item for item in cart.items if item.line_id == line_id), None)
    if item is None:
        raise ValueError("Unknown cart line. Use view_cart to find its line_id.")
    item.quantity = quantity
    item.line_total = round(item.unit_price * quantity, 2)
    state.refresh_deal(cart)
    return state.cart_to_dict(cart)


@mcp.tool()
def clear_cart(session_id: str) -> dict[str, Any]:
    """Remove all items and the deal when the customer asks to empty the cart. The selected delivery address is retained."""
    cart = state.get_cart(session_id)
    cart.items.clear()
    cart.applied_deal_id = None
    cart.deal_discount = 0.0
    return state.cart_to_dict(cart)

"""Lantern Pizza cart tools."""

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from agent_observability.pizza import state
from agent_observability.pizza.domain import Cart

mcp = FastMCP("Lantern Pizza Cart")


@mcp.tool(annotations={"readOnlyHint": True})
def view_cart(session_id: str) -> dict[str, Any]:
    """Show the cart: each line's line_id, quantity, the applied deal and totals. Read it before you edit items."""
    cart = state.sessions.get(session_id) or Cart(session_id=session_id)
    return state.cart_to_dict(cart)


@mcp.tool()
def set_cart_item_quantity(
    session_id: str, line_id: str, quantity: Annotated[int, Field(ge=0)]
) -> dict[str, Any]:
    """Set a cart line's total quantity to the customer's requested number. Quantity 0 removes the line. Use its line_id from view_cart; ask which variant if ambiguous."""
    cart = state.get_cart(session_id)
    item = next((item for item in cart.items if item.line_id == line_id), None)
    if item is None:
        raise ValueError("Unknown cart line. Use view_cart to find its line_id.")
    if quantity == 0:
        cart.items.remove(item)
    else:
        item.quantity = quantity
        item.line_total = round(item.unit_price * quantity, 2)
    # A deal stays only while the cart still has the items that it needs.
    state.refresh_deal(cart)
    return state.cart_to_dict(cart)

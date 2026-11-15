"""Lantern Pizza orders business actions."""

from typing import Any

from fastmcp import FastMCP

from agent_observability.pizza import state
from agent_observability.pizza.domain import Order

mcp = FastMCP("Lantern Pizza Orders")


# An order that is placed cannot be undone. The host reads this hint.
@mcp.tool(annotations={"destructiveHint": True})
def confirm_order(session_id: str) -> dict[str, Any]:
    """Place the mock order after customer approval. Requires a non-empty cart and a saved delivery address."""
    cart = state.get_cart(session_id)

    if not cart.items:
        raise ValueError("Cannot confirm an empty cart. Add items first.")
    if not cart.delivery_address:
        raise ValueError(
            "A delivery address is required. Ask the customer, then call set_delivery_address."
        )

    order = Order(session_id=session_id, cart=cart, delivery_fee=state.DELIVERY_FEE)
    state.orders[str(order.order_id)] = order
    # The cart is now an order. The next message of this chat starts a new cart.
    state.sessions.pop(session_id, None)

    return {
        "order_id": str(order.order_id),
        "status": "confirmed",
        "items": len(cart.items),
        "subtotal": cart.subtotal,
        "deal_discount": cart.deal_discount,
        "total": cart.total,
        "delivery_fee": order.delivery_fee,
        "grand_total": order.grand_total,
        "delivery_address": cart.delivery_address,
        "estimated_minutes": state.DELIVERY_MINUTES,
        "currency": state.CURRENCY,
        "message": (
            f"Order confirmed! Your pizza will arrive in {state.DELIVERY_MINUTES} minutes. "
            f"Total: €{order.grand_total:.2f}."
        ),
    }

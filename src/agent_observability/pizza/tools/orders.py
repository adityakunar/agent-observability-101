"""Lantern Pizza orders business actions."""

from typing import Any

from fastmcp import FastMCP

from agent_observability.pizza import state
from agent_observability.pizza.domain import Order
from agent_observability.pizza.enums import OrderStatus

mcp = FastMCP("Lantern Pizza Orders")


@mcp.tool()
def confirm_order(session_id: str) -> dict[str, Any]:
    """Place the mock order after customer approval. Requires a non-empty cart and an address the customer selected from the lookup results."""
    cart = state.get_cart(session_id)

    if not cart.items:
        raise ValueError("Cannot confirm an empty cart. Add items first.")
    if not cart.delivery_address:
        raise ValueError(
            "A customer-selected delivery address is required. Call lookup_delivery_addresses first."
        )

    fee = state.DELIVERY_FEE
    order = Order(session_id=session_id, cart=cart, delivery_fee=fee)
    state.orders[str(order.order_id)] = order

    grand_total = round(cart.total + fee, 2)

    state.sessions.pop(session_id, None)

    return {
        "order_id": str(order.order_id),
        "status": order.status.value,
        "items": len(cart.items),
        "subtotal": cart.subtotal,
        "deal_discount": cart.deal_discount,
        "total": cart.total,
        "delivery_fee": fee,
        "grand_total": grand_total,
        "delivery_address": cart.delivery_address.label if cart.delivery_address else None,
        "estimated_minutes": state.DELIVERY_MINUTES,
        "currency": state.CURRENCY,
        "message": (
            f"Order confirmed! Your pizza will arrive in 30–40 minutes. Total: €{grand_total:.2f}."
        ),
    }


def order_to_dict(order: Order) -> dict[str, Any]:
    return {
        "order_id": str(order.order_id),
        "status": order.status.value,
        "cart": state.cart_to_dict(order.cart),
        "delivery_fee": order.delivery_fee,
        "grand_total": order.grand_total,
        "currency": state.CURRENCY,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def view_orders(session_id: str) -> list[dict[str, Any]]:
    """Show confirmed and cancelled orders belonging to this chat, with full order_id values."""
    return [
        order_to_dict(order) for order in state.orders.values() if order.session_id == session_id
    ]


@mcp.tool()
def cancel_order(session_id: str, order_id: str) -> dict[str, Any]:
    """Cancel the demo order the customer explicitly asks to cancel. Use a full order_id from view_orders; ask which order if ambiguous. No payments or refunds occur."""
    order = state.orders.get(order_id)
    if order is None or order.session_id != session_id:
        raise ValueError("Order not found in this chat. Use view_orders for your order IDs.")
    order.status = OrderStatus.CANCELLED
    return {
        **order_to_dict(order),
        "message": "Demo order cancelled. No payment or refund occurred.",
    }

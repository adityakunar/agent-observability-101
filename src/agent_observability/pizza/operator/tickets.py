"""Turn business records into display values, without changing business state."""

from typing import Any

from agent_observability.pizza.domain import Cart, Order
from agent_observability.pizza.enums import OrderStatus
from agent_observability.pizza.menu_data import DEALS_BY_ID
from agent_observability.pizza.state import DELIVERY_FEE

from .lines import item_lines


def cart_ticket(sid: str, cart: Cart) -> dict[str, Any]:
    return {
        "session_id": sid,
        "item_count": len(cart.items),
        "lines": item_lines(cart),
        "subtotal": f"€{cart.subtotal:.2f}",
        "delivery_ready": bool(cart.items and cart.delivery_address),
        "delivery_fee": f"€{DELIVERY_FEE:.2f}",
        "grand_total": f"€{cart.total + DELIVERY_FEE:.2f}",
        "items_summary": ", ".join(f"{i.quantity} × {i.name}" for i in cart.items)
        if cart.items
        else "empty",
        "total": f"€{cart.total:.2f}",
        "deal": DEALS_BY_ID[cart.applied_deal_id].name
        if cart.applied_deal_id
        else "No deal applied",
        "discount": f"−€{cart.deal_discount:.2f}",
        "address": cart.delivery_address.label if cart.delivery_address else "No address selected",
        "check": "Add items to begin"
        if not cart.items
        else "Ready to review"
        if cart.delivery_address
        else "Waiting for customer address choice"
        if cart.address_candidates
        else "Delivery address needed",
        "variant": "success" if cart.items and cart.delivery_address else "warning",
    }


def order_ticket(oid: str, order: Order) -> dict[str, Any]:
    return {
        "order_id": oid[:8],
        "status": order.status.value,
        "variant": "success" if order.status == OrderStatus.CONFIRMED else "warning",
        "delivery_note": "30–40 min estimate"
        if order.status == OrderStatus.CONFIRMED
        else "Cancelled · no delivery",
        "total": f"€{order.grand_total:.2f}",
        "address": order.cart.delivery_address.label if order.cart.delivery_address else "—",
        "item_count": str(len(order.cart.items)),
        "lines": item_lines(order.cart),
        "subtotal": f"€{order.cart.subtotal:.2f}",
        "food_total": f"€{order.cart.total:.2f}",
        "session_id": order.session_id,
        "items_summary": ", ".join(f"{i.quantity} × {i.name}" for i in order.cart.items),
        "delivery_fee": f"€{order.delivery_fee:.2f}",
        "discount": f"−€{order.cart.deal_discount:.2f}",
    }

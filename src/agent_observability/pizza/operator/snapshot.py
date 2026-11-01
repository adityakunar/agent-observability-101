"""The operator reads one projection of carts, orders and observed FAQ calls."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from agent_observability.faq.activity import lookups
from agent_observability.pizza.enums import OrderStatus
from agent_observability.pizza.state import orders, sessions

from .tickets import cart_ticket, order_ticket


def get_operator_snapshot() -> dict[str, Any]:
    """Return a live snapshot of all active carts, confirmed orders, and FAQ lookups.

    Called by the operator view's SetInterval timer every 3 seconds.
    Display strings are pre-formatted server-side so the UI binds them
    directly without f-string expressions in reactive components.
    """
    return {
        "checked_at": datetime.now(ZoneInfo("Europe/Amsterdam")).strftime("%H:%M:%S"),
        "active_carts": [cart_ticket(sid, cart) for sid, cart in sessions.items()],
        "orders": [order_ticket(oid, order) for oid, order in orders.items()],
        "faq_activity": list(reversed(lookups[-10:])),
        "active_cart_count": len(sessions),
        "order_count": len(orders),
        "confirmed_order_count": sum(
            order.status == OrderStatus.CONFIRMED for order in orders.values()
        ),
        "faq_lookup_count": len(lookups),
    }

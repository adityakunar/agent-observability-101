"""Lantern Pizza deals tools."""

from typing import Any

from fastmcp import FastMCP

from agent_observability.pizza import state
from agent_observability.pizza.enums import Category
from agent_observability.pizza.menu_data import DEALS_BY_ID

mcp = FastMCP("Lantern Pizza Deals")


@mcp.tool()
def apply_deal(session_id: str, deal_id: str) -> dict[str, Any]:
    """Apply a bundle deal to the cart. Use browse_menu(category="deal") to see available deals. The meal_deal_standard requires 1 pizza + 1 side + 1 drink in the cart first."""
    deal = DEALS_BY_ID.get(deal_id)
    if deal is None:
        available = list(DEALS_BY_ID.keys())
        raise ValueError(f"Unknown deal: {deal_id!r}. Available deals: {available}")

    cart = state.get_cart(session_id)

    if cart.applied_deal_id is not None:
        raise ValueError(f"Deal {cart.applied_deal_id!r} is already applied. Cannot stack deals.")

    for cat_value, required_count in deal.required_categories.items():
        cat = Category(cat_value)
        actual = cart.item_count_by_category(cat)
        if actual < required_count:
            raise ValueError(
                f"Deal '{deal.name}' requires at least {required_count} {cat_value} item(s), "
                f"but the cart has {actual}. Add a {cat_value} item first."
            )

    if deal.discount_amount is not None:
        cart.deal_discount = deal.discount_amount
    elif deal.discount_percent is not None:
        cart.deal_discount = round(cart.subtotal * deal.discount_percent / 100, 2)

    cart.applied_deal_id = deal_id
    return {
        **state.cart_to_dict(cart),
        "deal_name": deal.name,
        "discount_applied": cart.deal_discount,
    }

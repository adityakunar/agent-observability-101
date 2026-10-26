"""Shared in-memory business state and representations for tools and the dashboard."""

from typing import Any

from agent_observability.pizza.domain import Cart, Deal, MenuItem, Order
from agent_observability.pizza.enums import Category
from agent_observability.pizza.menu_data import DEALS_BY_ID

CURRENCY = "EUR"
DELIVERY_FEE = 1.99
DELIVERY_MINUTES = "30-40"
sessions: dict[str, Cart] = {}
orders: dict[str, Order] = {}


def get_cart(session_id: str) -> Cart:
    if session_id not in sessions:
        sessions[session_id] = Cart(session_id=session_id)
    return sessions[session_id]


def cart_to_dict(cart: Cart) -> dict[str, Any]:
    return {
        "session_id": cart.session_id,
        "items": [
            {
                "line_id": i.line_id,
                "item_id": i.item_id,
                "name": i.name,
                "category": i.category.value,
                "size": i.size.value if i.size else None,
                "crust": i.crust.value if i.crust else None,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "line_total": i.line_total,
            }
            for i in cart.items
        ],
        "item_count": len(cart.items),
        "subtotal": cart.subtotal,
        "deal_discount": cart.deal_discount,
        "total": cart.total,
        "applied_deal_id": cart.applied_deal_id,
        "delivery_address": cart.delivery_address.label if cart.delivery_address else None,
        "currency": CURRENCY,
    }


def refresh_deal(cart: Cart) -> None:
    """Recheck eligibility after edits; discounts cannot outlive their bundle."""
    if cart.applied_deal_id is None:
        return
    deal = DEALS_BY_ID[cart.applied_deal_id]
    if any(
        cart.item_count_by_category(Category(category)) < count
        for category, count in deal.required_categories.items()
    ):
        cart.applied_deal_id = None
        cart.deal_discount = 0.0
    elif deal.discount_percent is not None:
        cart.deal_discount = round(cart.subtotal * deal.discount_percent / 100, 2)


def item_to_dict(item: MenuItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "category": item.category.value,
        "description": item.description,
        "prices": ({k.value: v for k, v in item.prices.items()} if item.prices else None),
        "price": item.price,
        "currency": CURRENCY,
        "allergens": item.allergens,
    }


def deal_to_dict(deal: Deal) -> dict[str, Any]:
    return {
        "id": deal.id,
        "name": deal.name,
        "category": Category.DEAL.value,
        "description": deal.description,
        "requires": dict(deal.required_categories),
        "discount_amount": deal.discount_amount,
        "currency": CURRENCY,
        "price": None,
        "prices": None,
        "allergens": [],
    }

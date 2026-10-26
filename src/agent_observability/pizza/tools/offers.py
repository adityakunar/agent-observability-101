"""Lantern Pizza offers tools."""

from typing import Any

from fastmcp import FastMCP

from agent_observability.pizza import state
from agent_observability.pizza.enums import Category
from agent_observability.pizza.menu_data import DEALS_BY_ID, MENU

mcp = FastMCP("Lantern Pizza Offers")


@mcp.tool(annotations={"readOnlyHint": True})
def get_meal_deal_offer(
    session_id: str, side_id: str | None = None, drink_id: str | None = None
) -> dict[str, Any]:
    """Quote the Standard Meal Deal without changing the cart. Pass side_id/drink_id only for the customer's choices. quote_kind is example while choices are missing, selected when their missing items are chosen, or already_eligible. Preserve existing items; never add an example as if the customer chose it."""
    cart = state.sessions.get(session_id)
    if cart is None or not cart.item_count_by_category(Category.PIZZA):
        return {"available": False, "reason": "Choose a pizza first."}
    if cart.applied_deal_id is not None:
        return {"available": False, "reason": "A deal is already applied; deals cannot stack."}
    deal = DEALS_BY_ID["meal_deal_standard"]
    missing: list[dict[str, Any]] = []
    additions: list[dict[str, Any]] = []
    choices = {"side": side_id, "drink": drink_id}
    selected = True
    additions_cost = 0.0
    for category, required in deal.required_categories.items():
        quantity = max(0, required - cart.item_count_by_category(Category(category)))
        choice = choices.get(category)
        if not quantity:
            if choice is not None and not any(item.item_id == choice for item in cart.items):
                raise ValueError(
                    f"The cart already has a {category}. Change that cart item first if the customer wants a different one."
                )
            continue
        options = [
            item
            for item in MENU
            if item.available and item.category.value == category and item.price is not None
        ]
        if not options:
            return {"available": False, "reason": "No available items complete this deal."}
        if choice is None:
            selected = False
            chosen = min(options, key=lambda item: (float(item.price or 0), item.id))
        else:
            match = next((item for item in options if item.id == choice), None)
            if match is None:
                raise ValueError(f"Choose an available {category} from the offer options.")
            chosen = match
        line_total = round(float(chosen.price or 0) * quantity, 2)
        additions_cost += line_total
        missing.append(
            {
                "category": category,
                "quantity": quantity,
                "options": [state.item_to_dict(item) for item in options],
            }
        )
        additions.append(
            {
                "item_id": chosen.id,
                "name": chosen.name,
                "quantity": quantity,
                "line_total": line_total,
            }
        )
    discount = deal.discount_amount or 0.0
    quoted_total = round(cart.total + additions_cost - discount, 2)
    return {
        "available": True,
        "deal_id": deal.id,
        "deal_name": deal.name,
        "qualifies_now": not missing,
        "missing": missing,
        "discount_amount": discount,
        "quote_kind": "already_eligible" if not missing else "selected" if selected else "example",
        "additions": additions,
        "current_food_total": cart.total,
        "quoted_food_total": quoted_total,
        "price_change": round(quoted_total - cart.total, 2),
        "currency": state.CURRENCY,
        "note": f"The price change applies to the listed additions only. An example includes items the customer has not chosen. The €{discount:.2f} saving compares the same bundle without the deal; adding items may increase the bill. Nothing has been added or applied.",
    }

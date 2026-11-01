"""Lantern Pizza menu business actions."""

from typing import Any

from fastmcp import FastMCP

from agent_observability.pizza import state
from agent_observability.pizza.enums import Category
from agent_observability.pizza.menu_data import DEALS, MENU

mcp = FastMCP("Lantern Pizza Menu")


@mcp.tool(annotations={"readOnlyHint": True})
def browse_menu(category: Category | None = None) -> list[dict[str, Any]]:
    """Browse the Lantern Pizza menu. Call this first before adding items. Optionally filter by category (pizza, side, drink, dessert, extra, deal). All prices are in EUR."""
    if category == Category.DEAL:
        return [state.deal_to_dict(deal) for deal in DEALS]
    items = MENU if category is None else [m for m in MENU if m.category == category]
    result = [state.item_to_dict(item) for item in items if item.available]
    if category is None:
        result.extend(state.deal_to_dict(deal) for deal in DEALS)
    return result

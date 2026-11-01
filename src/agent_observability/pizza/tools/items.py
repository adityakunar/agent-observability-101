"""Lantern Pizza items tools."""

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from agent_observability.pizza import state
from agent_observability.pizza.domain import CartItem
from agent_observability.pizza.enums import Category, Crust, Size
from agent_observability.pizza.menu_data import MENU_BY_ID

mcp = FastMCP("Lantern Pizza Items")


@mcp.tool()
def customize_and_add(
    session_id: str,
    pizza_id: str,
    size: Size,
    crust: Crust,
    quantity: Annotated[int, Field(ge=1)] = 1,
) -> dict[str, Any]:
    """Add the requested number of pizzas once. Ask for size and crust if missing; browse_menu supplies valid IDs. Use quantity for identical pizzas, never repeated calls."""
    item = MENU_BY_ID.get(pizza_id)
    if item is None:
        raise ValueError(f"Unknown pizza: {pizza_id!r}. Call browse_menu to see available items.")
    if item.category != Category.PIZZA:
        raise ValueError(f"{item.name!r} is not a pizza. Use add_extra for sides and drinks.")
    if item.prices is None or size not in item.prices:
        raise ValueError(f"Size {size.value!r} is not available for {item.name!r}.")

    unit_price = item.prices[size]
    cart_item = CartItem(
        item_id=pizza_id,
        name=item.name,
        category=Category.PIZZA,
        size=size,
        crust=crust,
        quantity=quantity,
        unit_price=unit_price,
        line_total=round(unit_price * quantity, 2),
    )
    cart = state.get_cart(session_id)
    cart.items.append(cart_item)
    return state.cart_to_dict(cart)


@mcp.tool()
def add_extra(
    session_id: str, item_id: str, quantity: Annotated[int, Field(ge=1)] = 1
) -> dict[str, Any]:
    """Add a side, drink, dessert, or extra (e.g. wings) to the cart. Not for pizzas — use customize_and_add instead."""
    item = MENU_BY_ID.get(item_id)
    if item is None:
        raise ValueError(f"Unknown item: {item_id!r}. Call browse_menu to see available items.")
    if item.category == Category.PIZZA:
        raise ValueError(f"{item.name!r} is a pizza. Use customize_and_add for pizzas.")
    if item.price is None:
        raise ValueError(f"{item.name!r} does not have a flat price.")

    cart_item = CartItem(
        item_id=item_id,
        name=item.name,
        category=item.category,
        quantity=quantity,
        unit_price=item.price,
        line_total=round(item.price * quantity, 2),
    )
    cart = state.get_cart(session_id)
    cart.items.append(cart_item)
    return state.cart_to_dict(cart)

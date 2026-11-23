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


@mcp.tool()
def change_pizza(
    session_id: str,
    line_id: str,
    pizza_id: str | None = None,
    size: Size | None = None,
    crust: Crust | None = None,
) -> dict[str, Any]:
    """Change a pizza in the cart in one step: another pizza, size or crust. Keeps the quantity. Give only what changes; the line_id is in the cart."""
    cart = state.get_cart(session_id)
    line = next((item for item in cart.items if item.line_id == line_id), None)
    if line is None or line.category != Category.PIZZA:
        raise ValueError("Unknown pizza line. The line_id of each cart line is in the cart.")
    new_id = pizza_id or line.item_id
    item = MENU_BY_ID.get(new_id)
    if item is None or item.category != Category.PIZZA:
        raise ValueError(f"Unknown pizza: {new_id!r}. Call browse_menu to see available items.")
    new_size, new_crust = size or line.size, crust or line.crust
    if item.prices is None or new_size not in item.prices:
        raise ValueError(f"Size {new_size!r} is not available for {item.name!r}.")
    line.item_id, line.name, line.size, line.crust = new_id, item.name, new_size, new_crust
    line.unit_price = item.prices[new_size]
    line.line_total = round(line.unit_price * line.quantity, 2)
    # A deal stays only while the cart still has the items that it needs.
    state.refresh_deal(cart)
    return state.cart_to_dict(cart)

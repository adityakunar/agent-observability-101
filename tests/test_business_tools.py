"""Cart edits through the composed MCP server: one tool sets, repeats and removes."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_observability.pizza import server, state


def setup_function():
    state.sessions.clear()
    state.orders.clear()


async def test_quantity_zero_removes_the_exact_variant_and_drops_an_ineligible_deal():
    async with Client(server.mcp) as client:
        for size in ("personal", "large"):
            await client.call_tool(
                "customize_and_add",
                {
                    "session_id": "cart",
                    "pizza_id": "margherita",
                    "size": size,
                    "crust": "thin",
                    "quantity": 2,
                },
            )
        for item in ("garlic_bread", "coke"):
            await client.call_tool("add_extra", {"session_id": "cart", "item_id": item})
        cart = (
            await client.call_tool(
                "apply_deal", {"session_id": "cart", "deal_id": "meal_deal_standard"}
            )
        ).data
        personal = cart["items"][0]["line_id"]
        large = cart["items"][1]["line_id"]
        result = (
            await client.call_tool(
                "set_cart_item_quantity",
                {"session_id": "cart", "line_id": personal, "quantity": 0},
            )
        ).data
        assert result["items"][0]["line_id"] == large
        assert result["items"][0]["quantity"] == 2
        assert result["deal_discount"] == 2  # a pizza, a side and a drink are still there
        side = result["items"][1]["line_id"]
        result = (
            await client.call_tool(
                "set_cart_item_quantity", {"session_id": "cart", "line_id": side, "quantity": 0}
            )
        ).data
        # No side: the deal cannot stay, and the customer pays the full price.
        assert result["applied_deal_id"] is None and result["deal_discount"] == 0
        assert result["total"] == 29.97


async def test_quantity_is_absolute_and_a_rejected_edit_preserves_the_cart():
    async with Client(server.mcp) as client:
        cart = (
            await client.call_tool(
                "customize_and_add",
                {"session_id": "cart", "pizza_id": "pepperoni", "size": "large", "crust": "thin"},
            )
        ).data
        line_id = cart["items"][0]["line_id"]
        # The same request two times gives 3, not 6. A repeated call does no harm.
        for _ in range(2):
            cart = (
                await client.call_tool(
                    "set_cart_item_quantity",
                    {"session_id": "cart", "line_id": line_id, "quantity": 3},
                )
            ).data
        assert cart["items"][0]["quantity"] == 3 and cart["subtotal"] == 44.97
        before = state.sessions["cart"].model_dump()
        for arguments in (
            {"line_id": line_id, "quantity": -1},
            {"line_id": "invented", "quantity": 1},
        ):
            with pytest.raises(ToolError):
                await client.call_tool(
                    "set_cart_item_quantity", {"session_id": "cart", **arguments}
                )
        assert state.sessions["cart"].model_dump() == before


async def test_each_chat_has_its_own_cart_and_its_own_order():
    async with Client(server.mcp) as client:
        for session, size in (("mine", "large"), ("other", "personal")):
            await client.call_tool(
                "customize_and_add",
                {"session_id": session, "pizza_id": "pepperoni", "size": size, "crust": "thin"},
            )
            await client.call_tool(
                "set_delivery_address", {"session_id": session, "address": "Damrak 1, Amsterdam"}
            )
        mine = (await client.call_tool("confirm_order", {"session_id": "mine"})).data
        # The order of one chat does not change the cart of a different chat.
        assert mine["grand_total"] == 16.98
        assert set(state.sessions) == {"other"} and len(state.orders) == 1
        other = (await client.call_tool("confirm_order", {"session_id": "other"})).data
        assert other["grand_total"] == 10.98 and other["order_id"] != mine["order_id"]
        assert {order.session_id for order in state.orders.values()} == {"mine", "other"}

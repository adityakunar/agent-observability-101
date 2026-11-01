"""Cart repair and order cancellation through the composed MCP server."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_observability.pizza import server, state
from agent_observability.pizza.operator.snapshot import get_operator_snapshot


def setup_function():
    state.sessions.clear()
    state.orders.clear()


async def test_remove_exact_variant_and_drop_ineligible_deal():
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
                "apply_deal",
                {
                    "session_id": "cart",
                    "deal_id": "meal_deal_standard",
                },
            )
        ).data
        personal = cart["items"][0]["line_id"]
        large = cart["items"][1]["line_id"]
        result = (
            await client.call_tool(
                "remove_cart_item",
                {
                    "session_id": "cart",
                    "line_id": personal,
                },
            )
        ).data
        assert result["items"][0]["line_id"] == large
        assert result["items"][0]["quantity"] == 2
        assert result["deal_discount"] == 2
        side = result["items"][1]["line_id"]
        result = (
            await client.call_tool(
                "remove_cart_item",
                {
                    "session_id": "cart",
                    "line_id": side,
                },
            )
        ).data
        assert result["applied_deal_id"] is None and result["deal_discount"] == 0
        assert result["total"] == 29.97
        before = state.sessions["cart"].model_dump()
        with pytest.raises(ToolError, match="Unknown cart line"):
            await client.call_tool(
                "remove_cart_item", {"session_id": "cart", "line_id": "invented"}
            )
        assert state.sessions["cart"].model_dump() == before


async def test_quantity_is_absolute_and_clear_cart_drops_discount():
    async with Client(server.mcp) as client:
        cart = (
            await client.call_tool(
                "customize_and_add",
                {
                    "session_id": "cart",
                    "pizza_id": "pepperoni",
                    "size": "large",
                    "crust": "thin",
                },
            )
        ).data
        line_id = cart["items"][0]["line_id"]
        for _ in range(2):
            cart = (
                await client.call_tool(
                    "set_cart_item_quantity",
                    {
                        "session_id": "cart",
                        "line_id": line_id,
                        "quantity": 3,
                    },
                )
            ).data
        assert cart["items"][0]["quantity"] == 3 and cart["subtotal"] == 44.97
        with pytest.raises(ToolError):
            await client.call_tool(
                "set_cart_item_quantity",
                {
                    "session_id": "cart",
                    "line_id": line_id,
                    "quantity": 0,
                },
            )
        for item in ("garlic_bread", "coke"):
            await client.call_tool("add_extra", {"session_id": "cart", "item_id": item})
        await client.call_tool(
            "apply_deal", {"session_id": "cart", "deal_id": "meal_deal_standard"}
        )
        cart = (await client.call_tool("clear_cart", {"session_id": "cart"})).data
        assert cart["items"] == [] and cart["total"] == 0 and cart["applied_deal_id"] is None


async def test_cancel_is_scoped_idempotent_and_keeps_history():
    async with Client(server.mcp) as client:
        for session in ("mine", "other"):
            await client.call_tool(
                "customize_and_add",
                {
                    "session_id": session,
                    "pizza_id": "pepperoni",
                    "size": "large",
                    "crust": "thin",
                },
            )
            await client.call_tool(
                "lookup_delivery_addresses",
                {
                    "session_id": session,
                    "street": "Damrak",
                    "house_number": "1",
                },
            )
            await client.call_tool(
                "select_delivery_address",
                {
                    "session_id": session,
                    "address_id": "0363200012113669",
                },
            )
            await client.call_tool("confirm_order", {"session_id": session})
        mine = (await client.call_tool("view_orders", {"session_id": "mine"})).data
        other = (await client.call_tool("view_orders", {"session_id": "other"})).data
        assert len(mine) == len(other) == 1
        with pytest.raises(ToolError, match="not found in this chat"):
            await client.call_tool(
                "cancel_order", {"session_id": "mine", "order_id": other[0]["order_id"]}
            )
        for _ in range(2):
            cancelled = (
                await client.call_tool(
                    "cancel_order",
                    {
                        "session_id": "mine",
                        "order_id": mine[0]["order_id"],
                    },
                )
            ).data
        assert cancelled["status"] == "cancelled" and cancelled["grand_total"] == 16.98
        assert len(state.orders) == 2
        snapshot = get_operator_snapshot()
        assert snapshot["confirmed_order_count"] == 1
        assert {order["status"] for order in snapshot["orders"]} == {"cancelled", "confirmed"}
        assert (await client.call_tool("view_orders", {"session_id": "other"})).data[0][
            "status"
        ] == "confirmed"

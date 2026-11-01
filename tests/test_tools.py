"""Business guarantees through real in-process MCP."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_observability.faq import server as faq
from agent_observability.faq.activity import lookups
from agent_observability.pizza import server, state
from agent_observability.pizza.operator.snapshot import get_operator_snapshot


def setup_function():
    state.sessions.clear()
    state.orders.clear()
    lookups.clear()


async def test_full_order_with_deal_delivery_fee_and_faq():
    async with Client(server.mcp) as client:
        menu = await client.call_tool("browse_menu", {})
        assert any(item["id"] == "pepperoni" for item in menu.data)
        await client.call_tool(
            "customize_and_add",
            {"session_id": "order", "pizza_id": "pepperoni", "size": "large", "crust": "thin"},
        )
        for item in ("garlic_bread", "coke"):
            await client.call_tool("add_extra", {"session_id": "order", "item_id": item})
        await client.call_tool(
            "apply_deal", {"session_id": "order", "deal_id": "meal_deal_standard"}
        )
        quote = await client.call_tool(
            "set_delivery_address", {"session_id": "order", "address": "Damrak 1, Amsterdam"}
        )
        assert quote.data["address"] == "Damrak 1, Amsterdam"
        assert quote.data["delivery_fee"] == 1.99
        facts = await client.call_tool("faq_read", {"filename": "allergen_info.md"})
        assert "garlic" in facts.data.lower()
        result = await client.call_tool("confirm_order", {"session_id": "order"})
    assert result.data["status"] == "confirmed"
    assert result.data["grand_total"] == 20.96
    assert result.data["deal_discount"] == 2.0
    assert result.data["currency"] == "EUR"
    assert "order" not in state.sessions and len(state.orders) == 1
    snapshot = get_operator_snapshot()
    assert snapshot["orders"][0]["total"] == "€20.96"
    assert snapshot["faq_activity"][0]["question"] == "Read allergen_info.md"


async def test_missing_prerequisites_preserve_cart():
    async with Client(server.mcp) as client:
        with pytest.raises(ToolError, match="empty"):
            await client.call_tool("confirm_order", {"session_id": "cart"})
        await client.call_tool(
            "customize_and_add",
            {"session_id": "cart", "pizza_id": "pepperoni", "size": "large", "crust": "thin"},
        )
        original = state.sessions["cart"].model_dump()
        with pytest.raises(ToolError, match="requires"):
            await client.call_tool(
                "apply_deal", {"session_id": "cart", "deal_id": "meal_deal_standard"}
            )
        with pytest.raises(ToolError, match="address"):
            await client.call_tool("confirm_order", {"session_id": "cart"})
    assert state.sessions["cart"].model_dump() == original
    assert not state.orders


async def test_address_is_saved_as_the_customer_gave_it_and_can_be_replaced():
    async with Client(server.mcp) as client:
        with pytest.raises(ToolError, match="empty"):
            await client.call_tool("set_delivery_address", {"session_id": "cart", "address": "  "})
        assert not state.sessions
        await client.call_tool(
            "set_delivery_address", {"session_id": "cart", "address": "  Damrak 1,   Amsterdam "}
        )
        assert state.sessions["cart"].delivery_address == "Damrak 1, Amsterdam"
        quote = (
            await client.call_tool(
                "set_delivery_address", {"session_id": "cart", "address": "Rokin 75, Amsterdam"}
            )
        ).data
    assert quote == {
        "address": "Rokin 75, Amsterdam",
        "delivery_fee": 1.99,
        "estimated_minutes": "30-40",
        "currency": "EUR",
    }
    assert state.sessions["cart"].delivery_address == "Rokin 75, Amsterdam"
    assert not state.orders


async def test_rejected_item_and_quantity_preserve_cart():
    async with Client(server.mcp) as client:
        await client.call_tool("add_extra", {"session_id": "cart", "item_id": "coke"})
        original = state.sessions["cart"].model_dump()
        for args in ({"item_id": "fries"}, {"item_id": "coke", "quantity": -1}):
            with pytest.raises(ToolError):
                await client.call_tool("add_extra", {"session_id": "cart", **args})
    assert state.sessions["cart"].model_dump() == original


async def test_the_catalog_is_nine_tools_and_reading_the_cart_creates_no_business_state():
    async with Client(server.mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert set(tools) == {
            "browse_menu",
            "customize_and_add",
            "add_extra",
            "view_cart",
            "set_cart_item_quantity",
            "apply_deal",
            "set_delivery_address",
            "confirm_order",
            "faq_read",
        }
        # The host reads this hint: it does not treat a read-only tool as a business action.
        read_only = {
            name
            for name, tool in tools.items()
            if tool.annotations and tool.annotations.read_only_hint
        }
        assert read_only == {"browse_menu", "view_cart", "faq_read"}
        cart = (await client.call_tool("view_cart", {"session_id": "new"})).data
        assert cart["items"] == [] and cart["total"] == 0
    assert not state.sessions and not state.orders


async def test_faq_retrieval_and_path_boundary(tmp_path, monkeypatch):
    (tmp_path / "facts.md").write_text("Garlic bread contains milk.\n")
    (tmp_path.parent / "outside.md").write_text("outside")
    (tmp_path / "escape.md").symlink_to(tmp_path.parent / "outside.md")
    monkeypatch.setattr(faq.settings, "knowledge_base_path", str(tmp_path))
    async with Client(server.mcp) as client:
        read = await client.call_tool("faq_read", {"filename": "facts.md"})
        assert "milk" in read.data
        # An unknown name gives the model the names that exist, so it can correct itself.
        with pytest.raises(ToolError, match="No document") as unknown:
            await client.call_tool("faq_read", {"filename": "allergens.md"})
        assert "facts.md" in str(unknown.value) and "escape.md" not in str(unknown.value)
        for filename in ("../outside.md", "escape.md"):
            with pytest.raises(ToolError, match="inside"):
                await client.call_tool("faq_read", {"filename": filename})

"""Business guarantees through real in-process MCP."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_observability.faq import server as faq
from agent_observability.faq.activity import lookups
from agent_observability.pizza import server, state
from agent_observability.pizza.operator.snapshot import get_operator_snapshot
from agent_observability.utilities import addresses as address_service


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
        matches = await client.call_tool(
            "lookup_delivery_addresses",
            {"session_id": "order", "street": "Damrk", "house_number": "1"},
        )
        assert matches.data["candidates"][0]["address"] == "Damrak 1, 1012 LG Amsterdam"
        assert not any(c["address"].startswith("Damrak 10,") for c in matches.data["candidates"])
        await client.call_tool(
            "select_delivery_address", {"session_id": "order", "address_id": "0363200012113669"}
        )
        facts = await client.call_tool(
            "faq_grep", {"query": "garlic", "filename": "allergen_info.md"}
        )
        assert any("garlic" in line.lower() for line in facts.data)
        result = await client.call_tool("confirm_order", {"session_id": "order"})
    assert result.data["status"] == "confirmed"
    assert result.data["grand_total"] == 20.96
    assert result.data["deal_discount"] == 2.0
    assert result.data["currency"] == "EUR"
    assert "order" not in state.sessions and len(state.orders) == 1
    snapshot = get_operator_snapshot()
    assert snapshot["orders"][0]["total"] == "€20.96"
    assert snapshot["faq_activity"][0]["tool"] == "faq_grep"


@pytest.mark.parametrize(
    "house_number,address_id,label",
    [
        (1, "0363200012113669", "Damrak 1, 1012 LG Amsterdam"),
        ("1", "0363200012113669", "Damrak 1, 1012 LG Amsterdam"),
        ("20A", "0363200000491693", "Damrak 20A, 1012 LH Amsterdam"),
    ],
)
async def test_lookup_accepts_numeric_and_text_house_numbers(house_number, address_id, label):
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "lookup_delivery_addresses",
            {"session_id": "cart", "street": "Damrak", "house_number": house_number},
        )
    assert result.data["candidates"] == [{"id": address_id, "address": label}]
    assert state.sessions["cart"].delivery_address is None
    assert not state.orders


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


async def test_new_lookup_invalidates_previous_address_until_customer_selects():
    async with Client(server.mcp) as client:
        await client.call_tool(
            "customize_and_add",
            {"session_id": "cart", "pizza_id": "pepperoni", "size": "large", "crust": "thin"},
        )
        await client.call_tool(
            "lookup_delivery_addresses",
            {"session_id": "cart", "street": "Damrak", "house_number": "1"},
        )
        await client.call_tool(
            "select_delivery_address", {"session_id": "cart", "address_id": "0363200012113669"}
        )
        original_items = state.sessions["cart"].items[:]
        lookup = await client.call_tool(
            "lookup_delivery_addresses",
            {
                "session_id": "cart",
                "street": "Nonexistent Restaurant Road",
                "house_number": "99999",
            },
        )
        assert lookup.data["candidates"] == []
        with pytest.raises(ToolError, match="address"):
            await client.call_tool("confirm_order", {"session_id": "cart"})
        assert state.sessions["cart"].items == original_items
        assert state.sessions["cart"].delivery_address is None
        await client.call_tool(
            "lookup_delivery_addresses",
            {"session_id": "cart", "street": "Damrak", "house_number": "1"},
        )
        with pytest.raises(ToolError, match="address"):
            await client.call_tool("confirm_order", {"session_id": "cart"})
        await client.call_tool(
            "select_delivery_address", {"session_id": "cart", "address_id": "0363200012113669"}
        )
        await client.call_tool("confirm_order", {"session_id": "cart"})
    assert len(state.orders) == 1


async def test_choice_must_belong_to_current_cart_lookup():
    async with Client(server.mcp) as client:
        await client.call_tool(
            "lookup_delivery_addresses",
            {"session_id": "one", "street": "Damrak", "house_number": "1"},
        )
        for session_id, address_id in [("one", "invented"), ("other", "0363200012113669")]:
            with pytest.raises(ToolError, match="current lookup"):
                await client.call_tool(
                    "select_delivery_address", {"session_id": session_id, "address_id": address_id}
                )
    assert all(cart.delivery_address is None for cart in state.sessions.values())
    assert not state.orders


async def test_lookup_outage_does_not_allow_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        address_service,
        "address_lookup",
        address_service.LocalAddressLookup(tmp_path / "missing.csv"),
    )
    async with Client(server.mcp) as client:
        await client.call_tool(
            "customize_and_add",
            {"session_id": "cart", "pizza_id": "pepperoni", "size": "large", "crust": "thin"},
        )
        with pytest.raises(ToolError, match="unavailable"):
            await client.call_tool(
                "lookup_delivery_addresses",
                {"session_id": "cart", "street": "Damrak", "house_number": "1"},
            )
        with pytest.raises(ToolError, match="address"):
            await client.call_tool("confirm_order", {"session_id": "cart"})
    assert len(state.sessions["cart"].items) == 1 and not state.orders


@pytest.mark.parametrize("street,number", [("", "1"), ("Damrak", "")])
async def test_lookup_requires_street_and_house_number(street, number):
    async with Client(server.mcp) as client:
        with pytest.raises(ToolError, match="street name and house number"):
            await client.call_tool(
                "lookup_delivery_addresses",
                {"session_id": "cart", "street": street, "house_number": number},
            )
    assert not state.orders


async def test_rejected_item_and_quantity_preserve_cart():
    async with Client(server.mcp) as client:
        await client.call_tool("add_extra", {"session_id": "cart", "item_id": "coke"})
        original = state.sessions["cart"].model_dump()
        for args in ({"item_id": "fries"}, {"item_id": "coke", "quantity": -1}):
            with pytest.raises(ToolError):
                await client.call_tool("add_extra", {"session_id": "cart", **args})
    assert state.sessions["cart"].model_dump() == original


async def test_read_only_cart_and_delivery_tools_do_not_create_business_state():
    async with Client(server.mcp) as client:
        cart = (await client.call_tool("view_cart", {"session_id": "new"})).data
        assert cart["items"] == [] and cart["total"] == 0
        assert (await client.call_tool("view_orders", {"session_id": "new"})).data == []
        assert not (await client.call_tool("get_meal_deal_offer", {"session_id": "new"})).data[
            "available"
        ]
        with pytest.raises(ToolError, match="choose a delivery address"):
            await client.call_tool("get_delivery_estimate", {"session_id": "new"})
    assert not state.sessions and not state.orders


async def test_faq_retrieval_and_path_boundary(tmp_path, monkeypatch):
    (tmp_path / "facts.md").write_text("Garlic bread contains milk.\n")
    (tmp_path.parent / "outside.md").write_text("outside")
    (tmp_path / "escape.md").symlink_to(tmp_path.parent / "outside.md")
    monkeypatch.setattr(faq.settings, "knowledge_base_path", str(tmp_path))
    async with Client(server.mcp) as client:
        read = await client.call_tool("faq_read", {"filename": "facts.md"})
        assert "milk" in read.data
        found = await client.call_tool("faq_find", {"pattern": "*"})
        assert found.data == ["facts.md"]
        for filename in ("../outside.md", "escape.md"):
            with pytest.raises(ToolError, match="inside"):
                await client.call_tool("faq_read", {"filename": filename})

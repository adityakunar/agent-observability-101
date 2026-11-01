"""Promotional claims come from a read-only price quote, not invented savings."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_observability.pizza import server, state


def setup_function():
    state.sessions.clear()
    state.orders.clear()


async def test_offer_requires_pizza_and_does_not_create_an_empty_cart():
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_meal_deal_offer", {"session_id": "dinner"})
    assert not result.data["available"] and not state.sessions


async def test_upsell_quote_reports_extra_cost_and_preserves_cart():
    async with Client(server.mcp) as client:
        await client.call_tool(
            "customize_and_add",
            {
                "session_id": "dinner",
                "pizza_id": "pepperoni",
                "size": "large",
                "crust": "thin",
            },
        )
        before = state.sessions["dinner"].model_dump()
        offer = (await client.call_tool("get_meal_deal_offer", {"session_id": "dinner"})).data
    assert offer["available"] and not offer["qualifies_now"]
    assert [item["item_id"] for item in offer["additions"]] == ["coleslaw", "water"]
    assert offer["current_food_total"] == 14.99
    assert offer["quoted_food_total"] == 16.47
    assert offer["price_change"] == 1.48 and offer["discount_amount"] == 2
    assert {item["category"] for item in offer["missing"]} == {"side", "drink"}
    assert state.sessions["dinner"].model_dump() == before
    assert not state.orders


async def test_eligible_offer_is_a_saving_and_applied_deal_is_not_offered_again():
    async with Client(server.mcp) as client:
        await client.call_tool(
            "customize_and_add",
            {
                "session_id": "dinner",
                "pizza_id": "pepperoni",
                "size": "large",
                "crust": "thin",
            },
        )
        for item in ("garlic_bread", "coke"):
            await client.call_tool("add_extra", {"session_id": "dinner", "item_id": item})
        before = state.sessions["dinner"].model_dump()
        offer = (await client.call_tool("get_meal_deal_offer", {"session_id": "dinner"})).data
        assert offer["qualifies_now"] and offer["missing"] == []
        assert offer["additions"] == [] and offer["price_change"] == -2
        assert offer["quoted_food_total"] == 18.97
        assert state.sessions["dinner"].model_dump() == before
        await client.call_tool("apply_deal", {"session_id": "dinner", "deal_id": offer["deal_id"]})
        applied = (await client.call_tool("get_meal_deal_offer", {"session_id": "dinner"})).data
        assert not applied["available"]


async def test_cart_with_a_drink_only_quotes_the_missing_side():
    async with Client(server.mcp) as client:
        for size, crust in [("personal", "original"), ("large", "thin")]:
            await client.call_tool(
                "customize_and_add",
                {
                    "session_id": "dinner",
                    "pizza_id": "pepperoni",
                    "size": size,
                    "crust": crust,
                },
            )
        await client.call_tool("add_extra", {"session_id": "dinner", "item_id": "coke"})
        before = state.sessions["dinner"].model_dump()
        offer = (await client.call_tool("get_meal_deal_offer", {"session_id": "dinner"})).data
    assert offer["current_food_total"] == 25.97
    assert offer["quoted_food_total"] == 26.46
    assert offer["price_change"] == 0.49
    assert [item["category"] for item in offer["missing"]] == ["side"]
    assert [item["item_id"] for item in offer["additions"]] == ["coleslaw"]
    assert state.sessions["dinner"].model_dump() == before


async def test_selected_quote_uses_customer_choices_and_marks_partial_choices_as_example():
    async with Client(server.mcp) as client:
        await client.call_tool(
            "customize_and_add",
            {
                "session_id": "dinner",
                "pizza_id": "pepperoni",
                "size": "large",
                "crust": "thin",
            },
        )
        before = state.sessions["dinner"].model_dump()
        partial = (
            await client.call_tool(
                "get_meal_deal_offer",
                {
                    "session_id": "dinner",
                    "side_id": "garlic_bread",
                },
            )
        ).data
        assert partial["quote_kind"] == "example"
        chosen = (
            await client.call_tool(
                "get_meal_deal_offer",
                {
                    "session_id": "dinner",
                    "side_id": "garlic_bread",
                    "drink_id": "coke",
                },
            )
        ).data
    assert chosen["quote_kind"] == "selected"
    assert [item["item_id"] for item in chosen["additions"]] == ["garlic_bread", "coke"]
    assert chosen["quoted_food_total"] == 18.97 and chosen["price_change"] == 3.98
    assert state.sessions["dinner"].model_dump() == before


async def test_quote_preserves_existing_drink_and_rejects_unknown_or_wrong_category_choices():
    async with Client(server.mcp) as client:
        await client.call_tool(
            "customize_and_add",
            {
                "session_id": "dinner",
                "pizza_id": "pepperoni",
                "size": "large",
                "crust": "thin",
            },
        )
        await client.call_tool("add_extra", {"session_id": "dinner", "item_id": "coke"})
        before = state.sessions["dinner"].model_dump()
        for choices in ({"side_id": "fries"}, {"side_id": "coke"}, {"drink_id": "water"}):
            with pytest.raises(ToolError):
                await client.call_tool("get_meal_deal_offer", {"session_id": "dinner", **choices})
        quote = (
            await client.call_tool(
                "get_meal_deal_offer",
                {
                    "session_id": "dinner",
                    "side_id": "coleslaw",
                    "drink_id": "coke",
                },
            )
        ).data
    assert quote["quote_kind"] == "selected" and quote["price_change"] == 0.49
    assert [item["item_id"] for item in quote["additions"]] == ["coleslaw"]
    assert state.sessions["dinner"].model_dump() == before

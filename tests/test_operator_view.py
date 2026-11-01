"""The operator can verify the same business changes the customer asked for."""

import re

import httpx2 as httpx
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


async def test_operator_distinguishes_variants_and_tracks_price_changes():
    async with Client(server.mcp) as client:
        for size, crust, quantity in [("personal", "original", 2), ("large", "thin", 1)]:
            await client.call_tool(
                "customize_and_add",
                {
                    "session_id": "dinner",
                    "pizza_id": "pepperoni",
                    "size": size,
                    "crust": crust,
                    "quantity": quantity,
                },
            )
        for item in ("garlic_bread", "coke"):
            await client.call_tool("add_extra", {"session_id": "dinner", "item_id": item})
        cart = (
            await client.call_tool(
                "apply_deal",
                {
                    "session_id": "dinner",
                    "deal_id": "meal_deal_standard",
                },
            )
        ).data
        before = get_operator_snapshot()["active_carts"][0]
        assert before["lines"][0] == {
            "title": "2 × Pepperoni",
            "variant": "Personal · Original crust",
            "unit_price": "€8.99 each",
            "line_total": "€17.98",
        }
        assert before["lines"][1]["variant"] == "Large · Thin crust"
        assert before["subtotal"] == "€38.95" and before["total"] == "€36.95"
        assert not before["delivery_ready"] and before["check"] == "Delivery address needed"
        await client.call_tool(
            "set_cart_item_quantity",
            {
                "session_id": "dinner",
                "line_id": cart["items"][0]["line_id"],
                "quantity": 1,
            },
        )
        await client.call_tool(
            "set_cart_item_quantity",
            {
                "session_id": "dinner",
                "line_id": cart["items"][2]["line_id"],
                "quantity": 0,
            },
        )
        after = get_operator_snapshot()["active_carts"][0]
        assert after["lines"][0]["title"] == "1 × Pepperoni"
        assert after["lines"][0]["line_total"] == "€8.99"
        assert all("Garlic Bread" not in line["title"] for line in after["lines"])
        assert after["deal"] == "No deal applied" and after["discount"] == "−€0.00"
        assert after["subtotal"] == after["total"] == "€25.97"
        for line in cart["items"][:2] + cart["items"][3:]:
            await client.call_tool(
                "set_cart_item_quantity",
                {"session_id": "dinner", "line_id": line["line_id"], "quantity": 0},
            )
        empty = get_operator_snapshot()["active_carts"][0]
        assert empty["lines"] == [] and empty["check"] == "Add items to begin"
        assert not empty["delivery_ready"] and empty["total"] == "€0.00"


async def test_operator_quote_and_confirmed_order_match_saved_business_state():
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
        snapshot = get_operator_snapshot()
        assert snapshot["active_carts"][0]["check"] == "Delivery address needed"
        await client.call_tool(
            "set_delivery_address", {"session_id": "dinner", "address": "Damrak 1, Amsterdam"}
        )
        ready = get_operator_snapshot()["active_carts"][0]
        assert ready["check"] == "Ready to review" and ready["delivery_ready"]
        assert ready["grand_total"] == "€16.98" and ready["delivery_fee"] == "€1.99"
        assert ready["address"] == "Damrak 1, Amsterdam"
        confirmed = (await client.call_tool("confirm_order", {"session_id": "dinner"})).data
        final = get_operator_snapshot()
        assert not final["active_carts"]
        [order] = final["orders"]
        # The order ticket shows the same lines and the same money as the cart did.
        assert order["lines"] == ready["lines"]
        assert order["total"] == ready["grand_total"] == f"€{confirmed['grand_total']:.2f}"
        assert order["food_total"] == ready["total"]
        assert order["status"] == "confirmed" and order["variant"] == "success"
        assert order["delivery_note"] == "30-40 min estimate"
        assert final["order_count"] == 1 and order["session_id"] == "dinner"


async def test_faq_view_shows_which_document_the_assistant_read_and_a_failed_lookup(
    tmp_path, monkeypatch
):
    (tmp_path / "allergens.md").write_text("Garlic bread contains milk.\nDough contains wheat.\n")
    monkeypatch.setattr(faq.settings, "knowledge_base_path", str(tmp_path))
    async with Client(server.mcp) as client:
        await client.call_tool("faq_read", {"filename": "allergens.md"})
        [read] = get_operator_snapshot()["faq_activity"]
        assert read["question"] == "Read allergens.md" and read["status"] == "Document read"
        assert read["documents"] == [{"filename": "allergens.md"}] and read["variant"] == "info"
        with pytest.raises(ToolError):
            await client.call_tool("faq_read", {"filename": "missing.md"})
        snapshot = get_operator_snapshot()
        failed = snapshot["faq_activity"][0]  # the newest lookup is first
        assert failed["question"] == "Read missing.md" and failed["status"] == "Lookup failed"
        assert failed["documents"] == [] and failed["variant"] == "warning"
        assert snapshot["faq_lookup_count"] == 2


async def _desk_get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=server.mcp.http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://desk") as client:
        return await client.get(path)


async def test_operator_source_reader_preserves_context_and_faq_path_boundary(
    tmp_path, monkeypatch
):
    original = "| Item | Milk | Wheat |\n| --- | --- | --- |\n| Garlic bread | yes | yes |\n"
    (tmp_path / "allergens.md").write_text(original)
    (tmp_path.parent / "outside.md").write_text("outside")
    (tmp_path / "escape.md").symlink_to(tmp_path.parent / "outside.md")
    monkeypatch.setattr(faq.settings, "knowledge_base_path", str(tmp_path))
    source = await _desk_get("/desk/sources/allergens.md")
    assert source.json() == {"filename": "allergens.md", "body": original}
    assert not lookups  # reading in the operator is not an assistant lookup
    for filename in ("..%2Foutside.md", "escape.md", "missing.md"):
        refused = await _desk_get(f"/desk/sources/{filename}")
        assert refused.status_code == 404 and "outside" not in refused.text
    async with Client(server.mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert not names & {"read_operator_source", "get_operator_snapshot"}


async def test_desk_page_works_offline_and_polls_the_live_snapshot():
    async with Client(server.mcp) as client:
        await client.call_tool("add_extra", {"session_id": "dinner", "item_id": "garlic_bread"})
    snapshot = (await _desk_get("/desk/snapshot")).json()
    assert snapshot["active_cart_count"] == 1
    page = await _desk_get("/")
    assert page.status_code == 200 and "/desk/snapshot" in page.text
    assert not re.search(r"<(script|link)[^>]+(src|href)=[\"']https?:", page.text, re.I)

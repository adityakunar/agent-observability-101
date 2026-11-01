"""The operator can verify the same business changes the customer asked for."""

import re

import httpx2 as httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_observability.faq import server as faq
from agent_observability.faq.activity import lookups
from agent_observability.pizza import server, state
from agent_observability.pizza.operator import model_server
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
            "remove_cart_item",
            {
                "session_id": "dinner",
                "line_id": cart["items"][2]["line_id"],
            },
        )
        after = get_operator_snapshot()["active_carts"][0]
        assert after["lines"][0]["title"] == "1 × Pepperoni"
        assert after["lines"][0]["line_total"] == "€8.99"
        assert all("Garlic Bread" not in line["title"] for line in after["lines"])
        assert after["deal"] == "No deal applied" and after["discount"] == "−€0.00"
        assert after["subtotal"] == after["total"] == "€25.97"
        await client.call_tool("clear_cart", {"session_id": "dinner"})
        empty = get_operator_snapshot()["active_carts"][0]
        assert empty["lines"] == [] and empty["check"] == "Add items to begin"
        assert not empty["delivery_ready"] and empty["total"] == "€0.00"


async def test_operator_quote_and_cancelled_order_match_saved_business_state():
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
        await client.call_tool(
            "lookup_delivery_addresses",
            {
                "session_id": "dinner",
                "street": "Damrk",
                "house_number": "1",
            },
        )
        snapshot = get_operator_snapshot()
        assert snapshot["active_carts"][0]["check"] == "Waiting for customer address choice"
        await client.call_tool(
            "select_delivery_address",
            {
                "session_id": "dinner",
                "address_id": "0363200012113669",
            },
        )
        ready = get_operator_snapshot()["active_carts"][0]
        assert ready["check"] == "Ready to review" and ready["delivery_ready"]
        assert ready["grand_total"] == "€16.98" and ready["delivery_fee"] == "€1.99"
        assert ready["address"] == "Damrak 1, 1012 LG Amsterdam"
        confirmed = (await client.call_tool("confirm_order", {"session_id": "dinner"})).data
        assert not get_operator_snapshot()["active_carts"]
        await client.call_tool(
            "cancel_order", {"session_id": "dinner", "order_id": confirmed["order_id"]}
        )
        final = get_operator_snapshot()
        [order] = final["orders"]
        assert order["lines"] == ready["lines"]
        assert order["total"] == ready["grand_total"]
        assert order["food_total"] == ready["total"]
        assert (
            order["status"] == "cancelled" and order["delivery_note"] == "Cancelled · no delivery"
        )
        assert order["variant"] == "warning" and final["confirmed_order_count"] == 0
        assert final["order_count"] == 1 and order["session_id"] == "dinner"


async def test_faq_view_distinguishes_evidence_no_match_listing_and_failure(tmp_path, monkeypatch):
    (tmp_path / "allergens.md").write_text("Garlic bread contains milk.\nDough contains wheat.\n")
    (tmp_path / "hours.md").write_text("Open for dinner.\n")
    monkeypatch.setattr(faq.settings, "knowledge_base_path", str(tmp_path))
    async with Client(server.mcp) as client:
        await client.call_tool("faq_grep", {"query": "milk"})
        [found] = get_operator_snapshot()["faq_activity"]
        assert found["sources"] == "allergens.md" and found["status"] == "1 matching passage(s)"
        assert found["question"] == "Searched for “milk”"
        assert found["passages"] == [
            {"where": "allergens.md · line 1", "text": "Garlic bread contains milk."}
        ]
        await client.call_tool("faq_grep", {"query": "peanuts"})
        missing = get_operator_snapshot()["faq_activity"][0]
        assert missing["status"] == "No matching passages" and missing["passages"] == []
        assert missing["variant"] == "warning"
        await client.call_tool("faq_ls", {})
        listed = get_operator_snapshot()["faq_activity"][0]
        assert listed["status"] == "2 document name(s) listed" and listed["passages"] == []
        await client.call_tool("faq_read", {"filename": "allergens.md"})
        read = get_operator_snapshot()["faq_activity"][0]
        assert read["status"] == "Document read" and read["sources"] == "allergens.md"
        with pytest.raises(ToolError):
            await client.call_tool("faq_read", {"filename": "missing.md"})
        failed = get_operator_snapshot()["faq_activity"][0]
        assert failed["status"] == "Lookup failed" and failed["sources"] == "No source retrieved"
        assert failed["passages"] == [] and failed["variant"] == "warning"


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
    assert "/desk/model-server" in page.text
    assert not re.search(r"<(script|link)[^>]+(src|href)=[\"']https?:", page.text, re.I)


async def test_model_server_panel_reports_server_wide_status_or_says_unavailable(monkeypatch):
    async def status(base_url, api_key):
        return {
            "status": "idle",
            "generation_tps": 41.25,
            "prompt_tps": 312.0,
            "total_requests_processed": 12,
            "metal": {"peak_memory_gb": 5.31},
        }

    monkeypatch.setattr(model_server, "read_status", status)
    assert (await _desk_get("/desk/model-server")).json() == {
        "available": True,
        "status": "idle",
        "generation": "41.2 tok/s",
        "prompt": "312.0 tok/s",
        "requests": "12",
        "memory": "5.3 GB peak",
    }

    async def missing(base_url, api_key):
        return None

    monkeypatch.setattr(model_server, "read_status", missing)
    assert await model_server.model_server_summary() == model_server.UNAVAILABLE

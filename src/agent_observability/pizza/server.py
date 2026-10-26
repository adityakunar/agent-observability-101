"""Compose business tools, FAQ observation and the operator's delivery desk."""

from fastmcp import FastMCP

from agent_observability.faq.activity import FaqActivityMiddleware
from agent_observability.faq.server import mcp as faq_mcp
from agent_observability.pizza.operator.routes import add_desk_routes
from agent_observability.pizza.tools import cart, deals, delivery, items, menu, offers, orders

mcp = FastMCP("Lantern Pizza")
for tool_server in (
    menu.mcp,
    items.mcp,
    deals.mcp,
    offers.mcp,
    cart.mcp,
    delivery.mcp,
    orders.mcp,
    faq_mcp,
):
    mcp.mount(tool_server)
mcp.add_middleware(FaqActivityMiddleware())
add_desk_routes(mcp)

if __name__ == "__main__":
    mcp.run(transport="http")

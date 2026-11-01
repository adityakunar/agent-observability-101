"""Compose business tools, FAQ observation and the operator's delivery desk."""

import uvicorn
from fastmcp import FastMCP

from agent_observability.faq.activity import FaqActivityMiddleware
from agent_observability.faq.server import mcp as faq_mcp
from agent_observability.netpolicy import LocalOnly
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
    # The desk and tools have no auth: bind to loopback so other machines cannot connect,
    # and wrap in LocalOnly so other websites in your browser cannot call them either.
    uvicorn.run(LocalOnly(mcp.http_app()), host="127.0.0.1", port=8000)

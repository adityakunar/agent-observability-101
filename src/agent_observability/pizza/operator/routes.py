"""Serve the delivery desk as one self-contained page beside the MCP endpoint."""

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from agent_observability.faq.server import faq_read

from .app import pizza_operator
from .model_server import model_server_summary
from .snapshot import get_operator_snapshot


def add_desk_routes(mcp: FastMCP) -> None:
    """Run the desk in the process that owns carts and orders; no MCP host or CDN needed."""

    @mcp.custom_route("/", methods=["GET"])
    async def desk(request: Request) -> Response:
        return HTMLResponse(pizza_operator().html(renderer_mode="bundled"))

    @mcp.custom_route("/desk/snapshot", methods=["GET"])
    async def snapshot(request: Request) -> Response:
        return JSONResponse(get_operator_snapshot())

    @mcp.custom_route("/desk/model-server", methods=["GET"])
    async def model_server(request: Request) -> Response:
        return JSONResponse(await model_server_summary())

    @mcp.custom_route("/desk/sources/{filename}", methods=["GET"])
    async def source(request: Request) -> Response:
        # Calls the function directly, so the operator's reading is not an assistant lookup.
        filename = request.path_params["filename"]
        try:
            body = faq_read(filename)
        except (ValueError, FileNotFoundError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return JSONResponse({"filename": filename, "body": body})

"""Observe FAQ calls at the MCP boundary, without changing their results."""

from typing import Any
from zoneinfo import ZoneInfo

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

lookups: list[dict[str, Any]] = []
_FAQ_ACTIVITY_MAX = 20


class FaqActivityMiddleware(Middleware):
    """Records recent FAQ lookups for the operator's delivery desk.

    Intercepts at the MCP protocol boundary so no logging code lives
    inside the tool functions themselves.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> Any:
        if context.message.name != "faq_read":
            return await call_next(context)
        filename = str((context.message.arguments or {}).get("filename", "a document"))
        # Start from "failed". The record changes only if the tool returns a document.
        activity: dict[str, Any] = {
            "question": f"Read {filename}",
            "timestamp": context.timestamp.astimezone(ZoneInfo("Europe/Amsterdam")).strftime(
                "%H:%M:%S"
            ),
            "status": "Lookup failed",
            "variant": "warning",
            "documents": [],
        }
        try:
            result = await call_next(context)
            activity.update(
                status="Document read", variant="info", documents=[{"filename": filename}]
            )
            return result
        finally:
            # finally also runs when the tool raises, so a failed lookup is recorded too.
            lookups.append(activity)
            del lookups[:-_FAQ_ACTIVITY_MAX]

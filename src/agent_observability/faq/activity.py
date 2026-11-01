"""Observe FAQ calls at the MCP boundary, without changing their results."""

from typing import Any
from zoneinfo import ZoneInfo

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

lookups: list[dict[str, Any]] = []
_FAQ_ACTIVITY_MAX = 20


def _question(name: str, args: dict[str, Any]) -> str:
    """Describe the lookup the way an operator would say it."""
    if name == "faq_grep":
        where = f" in {args['filename']}" if args.get("filename") else ""
        return f"Searched for “{args.get('query', '')}”{where}"
    if name == "faq_read":
        return f"Read {args.get('filename', 'a document')}"
    if name == "faq_find":
        return f"Looked for documents matching “{args.get('pattern', '')}”"
    return "Listed the FAQ documents"


def _passage(match: str) -> dict[str, str]:
    # faq_grep returns "file:line: text"; split it so the desk can show where it came from.
    filename, line, text = (match.split(":", 2) + ["", ""])[:3]
    return {"where": f"{filename} · line {line}", "text": text.strip()}


class FaqActivityMiddleware(Middleware):
    """Records recent FAQ retrieval outcomes for the operator dashboard.

    Intercepts at the MCP protocol boundary so no logging code lives
    inside the tool functions themselves.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: CallNext,
    ) -> Any:
        name: str = context.message.name
        if not name.startswith("faq_"):
            return await call_next(context)
        args = dict(context.message.arguments or {})
        activity: dict[str, Any] = {
            "tool": name,
            "question": _question(name, args),
            "timestamp": context.timestamp.astimezone(ZoneInfo("Europe/Amsterdam")).strftime(
                "%H:%M:%S"
            ),
            "status": "Lookup failed",
            "variant": "warning",
            "sources": "No source retrieved",
            "documents": [],
            "passages": [],
        }
        try:
            result = await call_next(context)
            data = (result.structured_content or {}).get("result")
            if name == "faq_grep":
                matches = data if isinstance(data, list) else []
                sources = sorted({str(match).split(":", 1)[0] for match in matches})
                activity.update(
                    status=f"{len(matches)} matching passage(s)"
                    if matches
                    else "No matching passages",
                    sources=", ".join(sources) if sources else "No matching source",
                    documents=[{"filename": filename} for filename in sources],
                    passages=[_passage(str(match)) for match in matches[:3]],
                    variant="info" if matches else "warning",
                )
            elif name == "faq_read":
                activity.update(
                    status="Document read",
                    sources=str(args["filename"]),
                    variant="info",
                    documents=[{"filename": str(args["filename"])}],
                )
            else:
                names = data if isinstance(data, list) else []
                activity.update(
                    status=f"{len(names)} document name(s) listed",
                    sources=", ".join(str(filename) for filename in names)
                    or "No document names found",
                    documents=[{"filename": str(filename)} for filename in names],
                    variant="info" if names else "warning",
                )
            return result
        finally:
            lookups.append(activity)
            del lookups[:-_FAQ_ACTIVITY_MAX]

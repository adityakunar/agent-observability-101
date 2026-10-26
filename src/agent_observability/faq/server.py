"""Read-only Markdown retrieval confined to the configured knowledge base."""

from pathlib import Path

from fastmcp import FastMCP

from agent_observability.config import settings
from agent_observability.utilities.resources import project_path

mcp = FastMCP("Lantern Pizza FAQ")


def _get_kb() -> Path:
    return project_path(settings.knowledge_base_path).resolve()


def _allow(filename: str) -> Path:
    root = _get_kb()
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or path.suffix != ".md":
        raise ValueError("Choose a Markdown document inside the knowledge base.")
    if not path.is_file():
        raise FileNotFoundError(filename)
    return path


@mcp.tool(annotations={"readOnlyHint": True})
def faq_ls() -> list[str]:
    """List available FAQ document names."""
    return sorted(p.name for p in _get_kb().glob("*.md") if p.resolve().is_relative_to(_get_kb()))


@mcp.tool(annotations={"readOnlyHint": True})
def faq_find(pattern: str) -> list[str]:
    """Find FAQ document names matching a glob, e.g. 'allergen*'."""
    from fnmatch import fnmatch

    return [name for name in faq_ls() if fnmatch(name, pattern)]


@mcp.tool(annotations={"readOnlyHint": True})
def faq_grep(query: str, filename: str | None = None) -> list[str]:
    """Search FAQ text; return source names, line numbers and matching lines."""
    files = [filename] if filename else faq_ls()
    return [
        f"{name}:{number}: {line}"
        for name in files
        for number, line in enumerate(_allow(name).read_text().splitlines(), 1)
        if query.lower() in line.lower()
    ]


@mcp.tool(annotations={"readOnlyHint": True})
def faq_read(filename: str) -> str:
    """Read an FAQ document when a targeted search needs surrounding context."""
    return _allow(filename).read_text()

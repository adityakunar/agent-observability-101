"""Read-only Markdown documents, confined to the configured knowledge base."""

from pathlib import Path

from fastmcp import FastMCP

from agent_observability.config import settings
from agent_observability.utilities.resources import project_path

mcp = FastMCP("Lantern Pizza FAQ")


def _get_kb() -> Path:
    return project_path(settings.knowledge_base_path).resolve()


def _allow(filename: str) -> Path:
    root = _get_kb()
    # resolve() follows ".." and symbolic links, so a name cannot point outside the folder.
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or path.suffix != ".md":
        raise ValueError("Choose a Markdown document inside the knowledge base.")
    if not path.is_file():
        names = sorted(p.name for p in root.glob("*.md") if p.resolve().is_relative_to(root))
        raise ValueError(f"No document {filename!r}. Documents: {', '.join(names)}")
    return path


@mcp.tool(annotations={"readOnlyHint": True})
def faq_read(filename: str) -> str:
    """Read one whole FAQ document, for example allergen_info.md. An unknown name returns the names of the documents."""
    return _allow(filename).read_text()

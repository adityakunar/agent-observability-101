"""The result of one customer turn."""

from dataclasses import dataclass, field


@dataclass
class Turn:
    text: str
    calls: list[str] = field(default_factory=list)
    coercions: int = 0
    exhausted: bool = False
    duplicates: int = 0
    error: str | None = None

"""Resolve bundled resources from the checkout, independent of the current directory."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def project_path(relative: str | Path) -> Path:
    path = Path(relative)
    return path if path.is_absolute() else PROJECT_ROOT / path

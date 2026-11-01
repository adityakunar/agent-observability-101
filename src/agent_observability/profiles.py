"""Named model profiles: one switch sets the endpoint, model, key source and allowlist.

``models.toml`` (committed) holds the shared profiles. ``models.local.toml`` (ignored by
git) can add profiles or override fields, for example ``key_expires``. Standard library only.
"""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agent_observability.netpolicy import LOOPBACK

FILES = (Path("models.toml"), Path("models.local.toml"))
FIELDS = {"base_url", "model", "keychain_service", "api_key_env", "temperature", "key_expires"}


class ProfileError(ValueError):
    """The profile is unknown or badly formed."""


def load(files: tuple[Path, ...] = FILES) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for path in files:
        if not path.exists():
            continue
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        for name, fields in data.items():
            if not isinstance(fields, dict):
                raise ProfileError(f"{path}: [{name}] must be a table")
            if unknown := set(fields) - FIELDS:
                raise ProfileError(f"{path}: [{name}] has unknown keys {sorted(unknown)}")
            profiles.setdefault(name, {}).update(fields)
    return profiles


def updates(name: str, allowed_hosts: str, profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Settings fields to replace for profile ``name``."""
    if name not in profiles:
        choices = ", ".join(sorted(profiles)) or "none (models.toml is missing)"
        raise ProfileError(f"Unknown model profile '{name}'. Choose one of: {choices}.")
    profile = profiles[name]
    if not profile.get("base_url") or not profile.get("model"):
        raise ProfileError(f"Profile '{name}' needs both base_url and model.")
    if str(profile["model"]).startswith("REPLACE"):
        raise ProfileError(f"Profile '{name}' has no model id yet; set it in models.toml.")
    result: dict[str, Any] = {
        "llm_base_url": str(profile["base_url"]),
        "llm_model": str(profile["model"]),
        "llm_keychain_service": profile.get("keychain_service"),
        "llm_api_key_env": profile.get("api_key_env"),
    }
    if "temperature" in profile:
        value = profile["temperature"]
        result["llm_temperature"] = None if value == "omit" else float(value)
    if "key_expires" in profile:
        expires = profile["key_expires"]
        result["llm_api_key_expires"] = (
            expires if isinstance(expires, date) else date.fromisoformat(str(expires))
        )
    host = (urlsplit(result["llm_base_url"]).hostname or "").lower()
    if host and host not in LOOPBACK:
        result["allowed_hosts"] = ",".join(filter(None, [allowed_hosts, host]))
    return result

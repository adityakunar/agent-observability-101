"""Read rapid-mlx's own /v1/status from a local server: MLX memory and serving rates."""

import math
from typing import Any

import httpx2 as httpx
from openai import AsyncOpenAI


async def read_status(base_url: str, api_key: str) -> dict[str, Any] | None:
    # Optional extension: never probe remote providers or follow redirects.
    root = httpx.URL(base_url.rstrip("/") + "/")
    if root.host not in {"localhost", "127.0.0.1", "::1"}:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=0.5, follow_redirects=False, trust_env=False
        ) as status:
            response = await status.get(
                str(root.join("status")), headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None  # Missing status support must not prevent a conversation.
    return body if isinstance(body, dict) else None


def number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value) if value >= 0 else None
    return None


async def read_mlx_peak(client: AsyncOpenAI) -> float | None:
    body = await read_status(str(client.base_url), client.api_key)
    metal = body.get("metal") if body else None
    return number(metal.get("peak_memory_gb")) if isinstance(metal, dict) else None

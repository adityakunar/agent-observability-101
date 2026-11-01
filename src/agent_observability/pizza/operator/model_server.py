"""What the local model server reports about itself, for the desk's Model server panel."""

from typing import Any

from agent_observability.config import llm_api_key, settings
from agent_observability.keys import KeyExpiredError, KeyMissingError
from agent_observability.llm.memory import number, read_status
from agent_observability.netpolicy import EgressDeniedError

UNAVAILABLE = {
    "available": False,
    "status": "No local rapid-mlx status",
    "generation": "—",
    "prompt": "—",
    "requests": "—",
    "memory": "—",
}


def _rate(value: Any) -> str:
    rate = number(value)
    return f"{rate:.1f} tok/s" if rate is not None else "—"


async def model_server_summary() -> dict[str, Any]:
    """Server-wide figures from rapid-mlx; they cover every request, not one conversation."""
    try:
        api_key = llm_api_key()
    except KeyExpiredError:
        return {**UNAVAILABLE, "status": "API key expired; run make rotate-key"}
    except KeyMissingError:
        return {**UNAVAILABLE, "status": "No key in the configured Keychain service"}
    except EgressDeniedError:
        return {**UNAVAILABLE, "status": "Model host not on the allowlist"}
    body = await read_status(settings.llm_base_url, api_key)
    if body is None:
        return UNAVAILABLE
    metal = body.get("metal")
    peak = number(metal.get("peak_memory_gb")) if isinstance(metal, dict) else None
    requests = number(body.get("total_requests_processed"))
    return {
        "available": True,
        "status": str(body.get("status", "unknown")),
        "generation": _rate(body.get("generation_tps")),
        "prompt": _rate(body.get("prompt_tps")),
        "requests": f"{requests:.0f}" if requests is not None else "—",
        "memory": f"{peak:.1f} GB peak" if peak is not None else "—",
    }

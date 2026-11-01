"""Translate provider replies and failures into the host's small contract."""

import json

import httpx2 as httpx
from openai import APIConnectionError, APIError, APIStatusError

from .contracts import ModelError, ToolCall


def parse_call(call_id: str, name: str, arguments: str) -> ToolCall:
    if not call_id or not name:
        raise ModelError("The model returned an incomplete tool call.")
    try:
        data = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        raise ModelError("The model returned invalid tool argument JSON.") from exc
    if not isinstance(data, dict):
        raise ModelError("The model's tool arguments must be a JSON object.")
    return ToolCall(call_id, name, data)


STREAM_FAILED = "The model connection failed during streaming. No pending tools were executed."


def request_error(error: Exception, endpoint: str) -> ModelError:
    if isinstance(error, APIConnectionError):
        return ModelError(f"Cannot reach the model at {endpoint}. Check your model endpoint.")
    if isinstance(error, APIStatusError):
        return ModelError(
            f"The model endpoint rejected the request (HTTP {error.status_code}). No pending tools were executed."
        )
    if isinstance(error, APIError):
        return ModelError("The model stream reported an error. No pending tools were executed.")
    if isinstance(error, httpx.HTTPError):
        return ModelError(STREAM_FAILED)
    return ModelError(
        "The model stream contained an invalid response. No pending tools were executed."
    )

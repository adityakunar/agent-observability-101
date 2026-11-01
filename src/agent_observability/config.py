"""Settings for the model API and the read-only knowledge base."""

from datetime import date
from functools import cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_observability import keys, netpolicy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_OBSERVABILITY_",
        env_file=(".env", ".env.local"),
        extra="ignore",
    )
    llm_base_url: str = "http://localhost:9000/v1"
    llm_model: str = "gemma-4-e4b-4bit"
    # Fallback only: on macOS the key comes from the Keychain (see keys.py).
    llm_api_key: SecretStr = SecretStr("not-needed")
    llm_api_key_expires: date | None = None
    # As in Lantern: a Keychain service holding the key under your macOS user (for example
    # "anthropic" or "nvidia"), and an optional variable that wins whenever it is set.
    llm_keychain_service: str | None = None
    llm_api_key_env: str | None = None
    # None leaves temperature out of the request; newer Claude models reject low values.
    llm_temperature: float | None = Field(default=0.2, ge=0, le=2)
    # Default-deny egress: non-loopback model hosts must be listed here (comma-separated).
    allowed_hosts: str = ""
    knowledge_base_path: str = "knowledge_base"
    # Model steps allowed per user message; guards against runaway tool loops.
    max_tool_iterations: int = Field(default=12, ge=1)
    max_tool_calls: int = Field(default=16, ge=1)
    streaming: bool = True

    @field_validator("llm_temperature", mode="before")
    @classmethod
    def _blank_temperature_is_none(cls, value: object) -> object:
        """An empty value (or "none") leaves temperature out, as Lantern's ``null`` does."""
        if isinstance(value, str) and value.strip().lower() in ("", "none", "null"):
            return None
        return value


settings = Settings()


def key_source() -> keys.KeySource:
    return keys.KeySource(settings.llm_keychain_service, settings.llm_api_key_env)


@cache
def llm_api_key() -> str:
    """Resolve once per process: Keychain, then env; raises keys.KeyExpiredError when expired.

    The key is released only for an allowlisted endpoint (netpolicy.EgressDeniedError otherwise).
    """
    key = keys.load_api_key(
        settings.llm_api_key.get_secret_value(), settings.llm_api_key_expires, key_source()
    )
    if key != keys.LOCAL_PLACEHOLDER:  # No key, nothing to leak: e.g. behind the egress proxy.
        allowed = netpolicy.parse_hosts(settings.allowed_hosts)
        netpolicy.check_endpoint(settings.llm_base_url, allowed)
    return key

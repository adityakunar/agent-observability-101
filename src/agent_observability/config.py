"""Settings for the model API and the read-only knowledge base."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_OBSERVABILITY_",
        env_file=(".env", ".env.local"),
        extra="ignore",
    )
    llm_base_url: str = "http://localhost:9000/v1"
    llm_model: str = "gemma-4-e4b-4bit"
    llm_api_key: SecretStr = SecretStr("not-needed")
    knowledge_base_path: str = "knowledge_base"
    # Model steps allowed per user message; guards against runaway tool loops.
    max_tool_iterations: int = Field(default=12, ge=1)
    max_tool_calls: int = Field(default=16, ge=1)
    streaming: bool = True


settings = Settings()

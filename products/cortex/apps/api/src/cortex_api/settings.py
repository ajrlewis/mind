from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr, StringConstraints, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    brain_url: HttpUrl | None = None
    brain_api_key: SecretStr | None = None
    brain_connect_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    brain_read_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    cortex_database_url: PostgresDsn = PostgresDsn(
        "postgresql+psycopg://brain:brain@localhost:5432/cortex"
    )
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout_seconds: float = Field(default=10, gt=0, le=60)
    database_pool_recycle_seconds: int = Field(default=1800, ge=30, le=86400)
    database_statement_timeout_ms: int = Field(default=30000, ge=100, le=120000)
    database_lock_timeout_ms: int = Field(default=5000, ge=100, le=30000)
    cortex_local_bearer_token: Annotated[str, StringConstraints(min_length=1, max_length=255)] = (
        "cortex-local-dev"
    )
    cortex_local_owner_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ] = "cortex-local-user"
    model_backend: Literal["deterministic", "openai"] = "deterministic"
    deterministic_stream_delay_seconds: float = Field(default=0, ge=0, le=5)
    openai_api_key: SecretStr | None = None
    openai_model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None = (
        None
    )
    openai_timeout_seconds: float = Field(default=30.0, ge=0.1, le=120)
    openai_base_url: HttpUrl | None = None
    openai_organization: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None
    ) = None
    openai_project: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None
    ) = None

    @model_validator(mode="after")
    def require_complete_brain_configuration(self) -> "Settings":
        if (self.brain_url is None) != (self.brain_api_key is None):
            raise ValueError("BRAIN_URL and BRAIN_API_KEY must be configured together")
        if self.model_backend == "openai":
            if self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip():
                raise ValueError("OPENAI_API_KEY is required for the OpenAI backend")
            if self.openai_model is None:
                raise ValueError("OPENAI_MODEL is required for the OpenAI backend")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

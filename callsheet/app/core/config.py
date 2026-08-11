"""Application settings, loaded once from the environment."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Every tunable value lives here — never as an inline literal in business logic."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "callsheet"
    environment: Literal["local", "test", "staging", "production"] = "local"

    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_format: Literal["json", "console"] = "json"

    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://callsheet:callsheet@localhost:5432/callsheet"
    database_echo: bool = False

    # NoDecode stops pydantic-settings from JSON-parsing the raw value, so the
    # validator below can accept the plain `A,B` form used in .env.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    monid_api_key: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_comma_separated_origins(cls, raw_value: object) -> object:
        """Accept `A,B` from the environment as well as a JSON list."""
        if isinstance(raw_value, str) and not raw_value.strip().startswith("["):
            return [origin.strip() for origin in raw_value.split(",") if origin.strip()]
        return raw_value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so the environment is parsed exactly once per process."""
    return Settings()

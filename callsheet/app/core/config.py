"""Application settings, loaded once from the environment."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.platforms import Platform

EndpointChoice = Literal["primary", "alternative"]


class PlatformEndpoints(BaseModel):
    """Which endpoints a platform may be served by, and which one is live.

    Both are configured up front so a switchover is a single value change made under
    pressure — an endpoint being deprecated is exactly when nobody wants to be looking up
    a vendor path. `active` names one of the two rather than holding a key of its own, so
    it is impossible to point a platform at an endpoint that was never vetted for it.
    """

    primary: str
    alternative: str | None = None
    active: EndpointChoice = "primary"

    @property
    def active_key(self) -> str | None:
        return self.primary if self.active == "primary" else self.alternative


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

    # Per-platform endpoint routing (E03-S07). Overridden as one JSON object, e.g.
    # COLLECTION_ENDPOINTS={"x":{"primary":"x.tikhub_search_timeline",
    #                            "alternative":"x.apify_tweet_scraper","active":"alternative"}}
    # which is the whole of "replace the X endpoint" — no code change, no redeploy of the
    # pipeline. Only X ships with a working adapter; the rest are routed here so the
    # configuration is complete before the adapters that read them exist.
    collection_endpoints: dict[Platform, PlatformEndpoints] = Field(
        default_factory=lambda: {
            Platform.X: PlatformEndpoints(
                primary="x.tikhub_search_timeline",
                alternative="x.apify_tweet_scraper",
            ),
            Platform.INSTAGRAM: PlatformEndpoints(
                primary="instagram.tikhub_hashtag_search",
                alternative="instagram.apify_hashtag_scraper",
            ),
            Platform.REDDIT: PlatformEndpoints(
                primary="reddit.tikhub_dynamic_search",
                alternative="reddit.apify_scraper_lite",
            ),
            Platform.YOUTUBE: PlatformEndpoints(
                primary="youtube.tikhub_video_comments",
                alternative="youtube.apify_comments_scraper",
            ),
        }
    )

    # Every page request carries this, and a PER_RESULT endpoint is refused without it.
    # One page of the size the live run returned (concept note §7 rule 2).
    collection_page_size: int = 20

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

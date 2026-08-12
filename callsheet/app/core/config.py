"""Application settings, loaded once from the environment."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.platforms import Platform

EndpointChoice = Literal["primary", "alternative"]

# The range a polling rate has to fall in to describe a schedule at all (E03-S01). Below
# one, a title is never polled; above roughly one poll every five minutes, "per day" stops
# describing a schedule and starts describing a continuous load. Defined here rather than
# in the cadence policy so configuration can be rejected at startup and the policy can
# enforce the same bound at runtime, without two different numbers.
MIN_POLLS_PER_DAY = 1
MAX_POLLS_PER_DAY = 288


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

    # Which platforms a cycle actually polls (E03-S01). Only X ships with adapters, and a
    # platform listed here without one is refused loudly rather than collecting nothing —
    # so this is the list that grows as adapters land, not `collection_endpoints`, which
    # describes routing for every platform whether or not it can be read yet.
    collection_platforms: Annotated[list[Platform], NoDecode] = Field(
        default_factory=lambda: [Platform.X]
    )

    # How many overlapping queries one cycle runs per platform (E03-S01). A cycle costs
    # variants x platforms calls, so this is the sharpest cost lever in the layer after
    # cadence. Five matches the story's worked example and the identity set the live run
    # was measured on.
    collection_variants_per_title: int = 5

    # The single default polling rate (E03-S01), in polls per day. This is the concept
    # note's *campaign* rate; E03-S02 replaces the whole policy with a phase-driven one
    # rather than changing this number.
    #
    # Bounded here so an unusable value fails at startup rather than per title per cycle.
    # Without it a typo is only caught when a finished cycle tries to queue its successor,
    # where it is swallowed and logged — leaving every title quietly stalled one cycle in,
    # which is a long way from the typo that caused it.
    collection_polls_per_day: int = Field(default=12, ge=MIN_POLLS_PER_DAY, le=MAX_POLLS_PER_DAY)

    # How many due cycles one worker tick claims, and how long it waits between ticks.
    collection_worker_batch_size: int = 5
    collection_worker_interval_seconds: int = 60

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_comma_separated_origins(cls, raw_value: object) -> object:
        """Accept `A,B` from the environment as well as a JSON list."""
        if isinstance(raw_value, str) and not raw_value.strip().startswith("["):
            return [origin.strip() for origin in raw_value.split(",") if origin.strip()]
        return raw_value

    @field_validator("collection_platforms", mode="before")
    @classmethod
    def split_comma_separated_platforms(cls, raw_value: object) -> object:
        """`COLLECTION_PLATFORMS=x,reddit` is the form anyone will actually type."""
        if isinstance(raw_value, str) and not raw_value.strip().startswith("["):
            return [name.strip() for name in raw_value.split(",") if name.strip()]
        return raw_value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so the environment is parsed exactly once per process."""
    return Settings()

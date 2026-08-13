"""Application settings, loaded once from the environment."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
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

    # Whether a title's rate follows its campaign phase (E03-S02). False binds the flat
    # policy at `collection_polls_per_day` instead — the escape hatch for a deployment
    # where adaptive cadence is the code path suspected of costing money, which has to be
    # one environment variable rather than a redeploy.
    collection_adaptive_cadence: bool = True

    # The three phase rates the concept note's §7 cost model is built on (E03-S02), and the
    # flat rate the opt-out above uses (E03-S01). All in polls per day.
    #
    # Bounded so an unusable value fails at startup rather than per title per cycle. Without
    # it a typo is only caught when a finished cycle tries to queue its successor, where it
    # is swallowed and logged — leaving every title quietly stalled one cycle in, which is a
    # long way from the typo that caused it.
    collection_polls_per_day: int = Field(default=12, ge=MIN_POLLS_PER_DAY, le=MAX_POLLS_PER_DAY)
    collection_dormant_polls_per_day: int = Field(
        default=2, ge=MIN_POLLS_PER_DAY, le=MAX_POLLS_PER_DAY
    )
    collection_campaign_polls_per_day: int = Field(
        default=12, ge=MIN_POLLS_PER_DAY, le=MAX_POLLS_PER_DAY
    )
    collection_surge_polls_per_day: int = Field(
        default=48, ge=MIN_POLLS_PER_DAY, le=MAX_POLLS_PER_DAY
    )

    # When observed volume overrides the calendar (E03-S02). A title escalates one phase
    # when its last `recent_hours` carry at least `minimum_mentions` posts *and* that is at
    # least `spike_multiplier` times its own daily mean over the `baseline_days` before.
    #
    # The floor is what stops a title going from one mention a day to four from buying surge
    # rates; the multiplier is what stops an ordinary campaign volume escalating permanently.
    collection_volume_spike_multiplier: float = Field(default=3.0, gt=1.0)
    collection_volume_spike_minimum_mentions: int = Field(default=25, ge=1)
    collection_volume_baseline_days: int = Field(default=14, ge=1)
    collection_volume_recent_hours: int = Field(default=24, ge=1)

    # What one poll costs, in USD (concept note §7: 5 variants x 5 pages across four
    # platforms). Configuration rather than a constant because it is a vendor price, and it
    # is the multiplier in every projection E09 shows.
    collection_cost_per_poll_usd: float = Field(default=0.225, gt=0)

    # **The hard page cap on a backfill** (E03-S03, concept note §7 rule 2).
    #
    # The single number that makes a historical range priceable. On a PER_CALL endpoint depth
    # *is* the cost, so an uncapped walk is an uncapped bill — and unlike a poll, a backfill
    # is asked for by someone who has been quoted a figure, which cannot be quoted at all
    # without this. Five pages is one hundred posts per query at the live capture's page
    # size, which for a five-variant title is a ceiling of 25 calls at $0.0015 — under four
    # cents, against a title budget of $273.
    #
    # Raising it raises the quote every studio sees before confirming, which is the intended
    # relationship: deeper history has a visible price rather than a silent one.
    collection_backfill_max_pages: int = Field(default=5, ge=1, le=50)

    # How many due cycles one worker tick claims, how long it waits between ticks, and how
    # many queued cycles it re-checks against the current cadence per tick (E03-S02).
    collection_worker_batch_size: int = 5
    collection_worker_interval_seconds: int = 60
    collection_cadence_reconcile_batch_size: int = Field(default=50, ge=0)

    # **When a platform counts as stale** (E03-S05), as a multiple of the interval implied by
    # the title's current cadence phase. Relative rather than absolute because the same
    # silence means different things at 2/day and 48/day — one absolute threshold would
    # scream through every quiet campaign or stay silent through an opening weekend.
    #
    # Two, not one. After one interval a poll is merely *due*, and a worker tick landing a
    # minute late is not a coverage gap. After two, a poll that should have happened has not.
    # Tighter than this and the indicator flaps, which is worse than having none — it only
    # works if being lit is believed.
    collection_staleness_interval_tolerance: float = Field(default=2.0, gt=1.0)

    # How many attempts back to look when counting a platform's consecutive failures, and how
    # many in a row raise an internal alert to data ops (E03-S05). Three, because one failed
    # poll is a blip and paging on it teaches an on-call rotation to filter the alert out.
    # Zero disables alerting without disabling the staleness reporting it sits beside.
    collection_platform_failure_window: int = Field(default=20, ge=1)
    collection_platform_failure_alert_threshold: int = Field(default=3, ge=0)

    # How many backfills one tick claims (E03-S03). One, because a backfill is the most
    # expensive single action in the product and a tick that took five would hold a worker
    # through five walks while every scheduled cycle behind them waited.
    collection_backfill_worker_batch_size: int = Field(default=1, ge=1)

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

    @model_validator(mode="after")
    def ensure_failure_window_can_reach_the_alert_threshold(self) -> "Settings":
        """A window shorter than the threshold can never alert, so it fails at startup.

        `consecutive_failures` reads at most `window` rows, so its value is capped there. Set
        a window of 2 against a threshold of 3 and the count can never equal the threshold —
        alerting silently switches itself off while every dashboard keeps reporting staleness
        correctly, which is the worst possible shape for this particular bug: the deployment
        looks fully instrumented and pages nobody.

        Refused here rather than defended at the call site, because the call site cannot tell
        a deliberate "alerting off" from a typo. Zero is the deliberate way off, and it is
        allowed.
        """
        threshold = self.collection_platform_failure_alert_threshold
        if threshold and self.collection_platform_failure_window < threshold:
            raise ValueError(
                "COLLECTION_PLATFORM_FAILURE_WINDOW "
                f"({self.collection_platform_failure_window}) must be at least "
                f"COLLECTION_PLATFORM_FAILURE_ALERT_THRESHOLD ({threshold}), or the "
                "failure count can never reach the threshold and no alert can ever fire. "
                "Set the threshold to 0 to turn alerting off deliberately."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so the environment is parsed exactly once per process."""
    return Settings()

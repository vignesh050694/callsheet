"""Request and response shapes for historical backfill (E03-S03)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.platforms import Platform
from app.models.collection_backfill import CollectionBackfillStatus


class BackfillRangeRequest(BaseModel):
    """The date range a studio is asking for, as two instants.

    Both required. A range with an open end would be a request to keep spending, and the
    screen that produces this always has two dates in it.
    """

    requested_from: datetime
    requested_until: datetime


class PlatformBackfillEstimateRead(BaseModel):
    """One platform's share of the quote, or why it has none."""

    platform: Platform
    endpoint_key: str | None
    price_model: str | None
    calls: int
    max_cost_usd: float
    # Set when this platform cannot be collected from at all. Carried rather than dropped so
    # the screen can say "Instagram will not be included" instead of quietly quoting for
    # three platforms while the studio believes they are buying four.
    unavailable_reason: str | None


class BackfillEstimateRead(BaseModel):
    """What a range would cost, before anything is spent.

    Every figure is a **ceiling**. The walk stops early whenever a provider runs out of
    pages or the range is covered, which is the common case — so the charge is usually
    lower, and never higher.
    """

    title_id: uuid.UUID
    requested_from: datetime
    requested_until: datetime

    variants: int = Field(
        description="How many distinct queries this title's identity set produces."
    )
    pages_per_query: int = Field(
        description="The hard page cap. On a per-call endpoint this is the whole cost lever."
    )
    page_size: int
    max_calls: int
    max_cost_usd: float
    platforms: list[PlatformBackfillEstimateRead]


class BackfillRead(BaseModel):
    """One backfill request, and what it actually managed to collect."""

    id: uuid.UUID
    title_id: uuid.UUID
    status: CollectionBackfillStatus

    requested_from: datetime
    requested_until: datetime

    # The quote as it stood when this was confirmed, not as it would be recomputed now.
    page_cap: int
    estimated_calls: int
    estimated_max_cost_usd: float

    pages_fetched: int
    # Deliberately named for what it is. Account-type segmentation arrives with E04-S03, so
    # this counts every historical post collected — organic, trade, owned media and
    # promotional alike — and no consumer should render it as a measure of public
    # conversation.
    unsegmented_mentions_stored: int = Field(
        description="Historical mentions newly stored, with no account-type segmentation."
    )
    mentions_already_known: int = Field(
        description="Posts in the range this title already held; collected again, stored once."
    )
    unreadable: int
    charged_cost_usd: float

    # **The depth actually achieved**, which is the point of the story rather than a detail
    # of it. `earliest_posted_at` is the oldest post any query reached; `is_depth_limited`
    # says whether that fell short of `requested_from`.
    earliest_posted_at: datetime | None
    is_depth_limited: bool = Field(
        description=(
            "True when the range asked for was not reached in full — the platform stopped "
            "serving history, or the page cap was hit. Never suppress this in a chart that "
            "covers the range."
        )
    )
    has_reached_page_cap: bool

    started_at: datetime | None
    finished_at: datetime | None
    failure_reason: str | None

    created_at: datetime

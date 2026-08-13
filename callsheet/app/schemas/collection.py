"""Response shapes for collection status.

E03-S01 shipped the title-level view, E03-S02 added the cadence phase, and E03-S05 added the
per-platform coverage the title-level view cannot express — a cycle where three platforms
worked and one did not is a success by every field above `platforms`.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.cadence_phase import CadencePhase
from app.core.collection_health import PlatformHealthState
from app.models.collection_run import CollectionRunStatus


class PlatformHealthRead(BaseModel):
    """One platform's collection health for one title (E03-S05).

    The dashboard header's per-platform line. `state` is the field to branch on; the two
    beside it exist so a stale platform can say when it last worked and what went wrong,
    rather than only that something did.
    """

    platform: str
    state: PlatformHealthState
    last_successful_at: datetime | None = Field(
        description="Last successful collection for this platform, or null if never."
    )
    last_failure_reason: str | None
    consecutive_failures: int = Field(
        description="Attempts failed in a row. Only counted while the platform is not reporting."
    )


class TitleCollectionStatusRead(BaseModel):
    """What the setup screen needs to say whether a title is collecting."""

    title_id: uuid.UUID

    # Deliberately named for what it is. Account-type segmentation arrives with E04-S03,
    # so this counts every post collected — organic, trade, owned media and promotional
    # alike — and no consumer should render it as a measure of public conversation.
    unsegmented_mention_count: int = Field(
        description="Every mention collected, with no account-type segmentation applied yet."
    )

    finished_run_count: int
    last_finished_at: datetime | None
    last_run_status: CollectionRunStatus | None
    last_run_failure_reason: str | None
    next_run_at: datetime | None

    # The rate and the phase that set it (E03-S02). Both describe the title *now* rather
    # than the queued cycle, so a title that has just crossed into its release-surge window
    # reads as surging on the next render rather than after the next poll.
    polls_per_day: int = Field(
        description="Polls per day this title is currently on, from its cadence phase."
    )
    cadence_phase: CadencePhase
    is_volume_escalated: bool = Field(
        description=(
            "True when observed volume, not the calendar, is what raised this title's rate."
        )
    )

    latest_mention_posted_at: datetime | None

    # Derived server-side rather than left to each client. Two screens computing "is this
    # still starting up?" from raw counts is two chances to disagree about what an empty
    # dashboard means.
    is_awaiting_first_results: bool
    is_stalled: bool

    # Per-platform coverage (E03-S05).
    platforms: list[PlatformHealthRead]
    data_as_of: datetime | None = Field(
        default=None,
        description=(
            "How current the data is, over the platforms that are actually reporting — the "
            "oldest of their last successful collections, never the newest. Null when "
            "nothing is reporting, which must render as 'no current data' rather than as an "
            "invented timestamp. Any platform listed as stale is excluded from this claim "
            "and must be named separately wherever its data appears."
        ),
    )

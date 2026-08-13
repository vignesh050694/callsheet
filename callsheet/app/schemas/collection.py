"""Response shapes for collection status (E03-S01, cadence phase added by E03-S02)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.cadence_phase import CadencePhase
from app.models.collection_run import CollectionRunStatus


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

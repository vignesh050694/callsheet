"""Response shapes for collection status (E03-S01)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

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
    polls_per_day: int | None
    latest_mention_posted_at: datetime | None

    # Derived server-side rather than left to each client. Two screens computing "is this
    # still starting up?" from raw counts is two chances to disagree about what an empty
    # dashboard means.
    is_awaiting_first_results: bool
    is_stalled: bool

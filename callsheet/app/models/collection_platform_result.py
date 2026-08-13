"""What each platform did in each cycle (E03-S05).

Until this table, a cycle recorded one outcome for all four platforms at once. That is
enough to answer "is this title collecting" and useless for the question this story asks —
"is *Instagram* collecting" — because a cycle in which three platforms worked and one failed
is recorded as a success, which is exactly the shape of the failure the story is about. The
counters on `collection_runs` are a title's totals; these are the same cycle broken out by
the axis a coverage gap actually happens on.

A log rather than a current-state row per platform, and the extra rows buy two things a
snapshot cannot. **Repeated** failure is the alerting signal the story's Notes ask for — one
failed poll is a blip and six in a row is an outage, and telling them apart needs the
history. And a studio asking why release weekend looks thin needs to see when the gap opened,
not merely that one is open now.

`finished_at` is when the attempt ended, and the last row with `SUCCEEDED` is the
"last successful collection" the dashboard header shows. Nothing derives freshness from
`created_at`: it is a server default, and Postgres `now()` is transaction-start time while
SQLite's has one-second resolution — the trap `mention_repository` records at length.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.platforms import Platform
from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

FAILURE_REASON_MAX_LENGTH = 500


class PlatformCollectionStatus(enum.StrEnum):
    """How one platform fared in one cycle.

    Three outcomes rather than two, because the difference between them is the difference
    between a page somebody should look at and a page nobody needs to. What they share is
    what the dashboard reads: only `SUCCEEDED` counts as the platform reporting.
    """

    SUCCEEDED = "succeeded"
    # The platform could not be reached at all — no endpoint configured, no adapter for the
    # one that is, or a transport that refused. This is the shape "Instagram's endpoint is
    # down" actually arrives in, and it is the story's scenario.
    UNAVAILABLE = "unavailable"
    # Something unexpected escaped the poll. Distinct from UNAVAILABLE because a typed
    # refusal is a configuration answer and this is a bug or an outage nobody predicted.
    FAILED = "failed"

    @property
    def is_reporting(self) -> bool:
        return self is PlatformCollectionStatus.SUCCEEDED


class CollectionPlatformResult(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "collection_platform_results"
    __table_args__ = (
        # The read behind "when did this platform last succeed for this title" — every
        # question this story asks is scoped to one title and one platform, newest first.
        Index(
            "ix_collection_platform_result_title_platform_finished",
            "title_id",
            "platform",
            "finished_at",
        ),
        Index("ix_collection_platform_result_run", "collection_run_id"),
    )

    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("collection_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[Platform] = mapped_column(
        SqlEnum(Platform, name="platform", native_enum=False),
        nullable=False,
    )
    status: Mapped[PlatformCollectionStatus] = mapped_column(
        SqlEnum(
            PlatformCollectionStatus,
            name="platform_collection_status",
            native_enum=False,
        ),
        nullable=False,
    )

    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mentions_stored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    failure_reason: Mapped[str | None] = mapped_column(
        String(FAILURE_REASON_MAX_LENGTH), nullable=True
    )

    # Set by the application at the moment the attempt ended — never a server default, for
    # the reason in the module docstring.
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<CollectionPlatformResult {self.platform}:{self.status} title={self.title_id}>"

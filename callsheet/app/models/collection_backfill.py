"""One request to collect a stretch of the past (E03-S03).

Separate from `collection_runs` rather than another trigger on it, because the two answer
different questions and cannot share a queue. A cycle asks "what is being said now" and is
owed on a cadence; a backfill asks "what was said between these two dates", is asked for
once by a person, and carries a price that person agreed to. Most concretely,
`uq_collection_run_one_pending_per_title` allows a title exactly one pending cycle — putting
a backfill in that table would mean a studio could not ask for history without stopping
their live collection, or the constraint that keeps a title from being double-polled would
have to be weakened to permit it.

The row is also the receipt. What was asked for, what it was quoted at, what it actually
cost, and — the field the story is most insistent about — **how far back it really got**.
Search endpoints return what they choose to return, so a backfill that asked for six weeks
and reached eleven days must say eleven days. Reporting the request back as if it were the
result is the exact failure concept note §6.4 rules out.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    false,
    text,
)
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.title import Title

FAILURE_REASON_MAX_LENGTH = 500


class CollectionBackfillStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    # Ran to the end. It does *not* mean the whole requested range was covered — that is
    # `is_depth_limited`, and the two are separate because a backfill that reached eleven
    # days of the six weeks asked for did nothing wrong; the platform did.
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # Claimed and deliberately not attempted — a spend ceiling (E09), or no platform with a
    # usable route. Nothing went wrong and nothing needs investigating.
    SKIPPED = "skipped"

    @property
    def is_pending(self) -> bool:
        return self in (CollectionBackfillStatus.QUEUED, CollectionBackfillStatus.RUNNING)

    @property
    def is_finished(self) -> bool:
        return not self.is_pending


_PENDING_STATUS_SQL = ", ".join(
    f"'{status.name}'"
    for status in (CollectionBackfillStatus.QUEUED, CollectionBackfillStatus.RUNNING)
)
_ONE_PENDING_BACKFILL_PREDICATE = text(f"status IN ({_PENDING_STATUS_SQL})")


class CollectionBackfill(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "collection_backfills"
    __table_args__ = (
        # The claim query: queued work, oldest first.
        Index("ix_collection_backfill_status_created_at", "status", "created_at"),
        # The read behind the title's backfill history, newest first.
        Index("ix_collection_backfill_title_created_at", "title_id", "created_at"),
        # **One pending backfill per title, enforced by the database.**
        #
        # A backfill is the only thing in this product that spends a lump of money because
        # somebody pressed a button, and a double-click on a slow connection is the ordinary
        # way to press it twice. The service checks first, but a check followed by an insert
        # is two requests both seeing nothing pending — and the failure is not a duplicate
        # row, it is a duplicate invoice.
        Index(
            "uq_collection_backfill_one_pending_per_title",
            "title_id",
            unique=True,
            postgresql_where=_ONE_PENDING_BACKFILL_PREDICATE,
            sqlite_where=_ONE_PENDING_BACKFILL_PREDICATE,
        ),
    )

    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Who agreed to the cost. Kept when the user is deleted rather than cascading the row
    # away, because the spend happened and the receipt has to outlive the account.
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # What was asked for. Half-open, `requested_from` inclusive.
    requested_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[CollectionBackfillStatus] = mapped_column(
        SqlEnum(CollectionBackfillStatus, name="collection_backfill_status", native_enum=False),
        nullable=False,
        default=CollectionBackfillStatus.QUEUED,
    )

    # The quote, stamped at request time rather than recomputed on read. Prices, the page cap
    # and the identity set can all move between asking and running, and the number a studio
    # confirmed against is the one that has to be shown back to them.
    page_cap: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_max_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # What it did.
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mentions_stored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mentions_already_known: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unreadable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    charged_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # **The depth actually achieved**, which is the field this story exists around. The
    # oldest post any query reached, and whether that fell short of what was asked for.
    earliest_posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_depth_limited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    # Why it fell short, when it did: the product's own cap rather than the platform's
    # depth. Separated because only one of the two is something an operator can change.
    has_reached_page_cap: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(
        String(FAILURE_REASON_MAX_LENGTH), nullable=True
    )

    title: Mapped[Title] = relationship(lazy="raise")

    def __repr__(self) -> str:
        return (
            f"<CollectionBackfill {self.status} title={self.title_id} "
            f"from={self.requested_from} until={self.requested_until}>"
        )

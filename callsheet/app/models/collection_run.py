"""The polling queue: one row per collection cycle a title is owed (E03-S01).

A table rather than an in-process timer, because the promise this story makes is that
collection starts *without anyone provisioning a job*. An in-memory schedule keeps that
promise only until the process restarts, and a title whose poll was lost with a deploy
looks identical to a title nobody is talking about.

The row is also the record. `scheduled_for` is when the cycle became due, `started_at`
when a worker claimed it, and the counters are what E03-S05 will report coverage from and
what E09 will cost. `polls_per_day` is stamped on the run rather than read back from
configuration, so a rate that changes mid-campaign (E03-S02) leaves a truthful history of
what was actually paid for.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.title import Title

FAILURE_REASON_MAX_LENGTH = 500


class CollectionRunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    # Claimed, found ineligible, and deliberately not attempted — a spend ceiling
    # (E09) or a platform with no adapter. Distinct from FAILED because nothing went
    # wrong and nothing needs investigating; the next cycle is still queued.
    SKIPPED = "skipped"

    @property
    def is_pending(self) -> bool:
        """Owed but not yet finished — the states that must not be double-queued."""
        return self in (CollectionRunStatus.QUEUED, CollectionRunStatus.RUNNING)

    @property
    def is_finished(self) -> bool:
        return not self.is_pending


class CollectionRunTrigger(enum.StrEnum):
    # The first run of a title's life, queued inside the transaction that created it.
    TITLE_CREATED = "title_created"
    # Every run after that, queued by the cadence policy as the previous one finishes.
    SCHEDULED = "scheduled"
    # An operator asked for one out of band.
    MANUAL = "manual"


# The literal values a pending status has *in the database*. SQLAlchemy's `Enum` persists
# a Python enum's member name rather than its value, so these are "QUEUED"/"RUNNING" and
# not "queued"/"running". Derived from the members rather than typed out, so the partial
# index below cannot drift from the enum it filters on.
_PENDING_STATUS_SQL = ", ".join(
    f"'{status.name}'" for status in (CollectionRunStatus.QUEUED, CollectionRunStatus.RUNNING)
)
_ONE_PENDING_RUN_PREDICATE = text(f"status IN ({_PENDING_STATUS_SQL})")


class CollectionRun(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "collection_runs"
    __table_args__ = (
        # The claim query: due work, oldest first. Status leads because a worker asks
        # "what is queued" far more often than it asks about any one title.
        Index("ix_collection_run_status_scheduled_for", "status", "scheduled_for"),
        # The read behind "when did this title last collect, and when is it next due".
        Index("ix_collection_run_title_scheduled_for", "title_id", "scheduled_for"),
        # **One pending cycle per title, enforced by the database.**
        #
        # The service checks this before inserting, but a check followed by an insert is
        # not a guarantee — two processes both read "nothing pending" and both queue one.
        # That is reachable through shipped paths: the worker queues a successor as a cycle
        # finishes while an operator runs `--title-id` beside it. The result is a title
        # polled twice per cycle at twice the cost, and two workers claiming both rows and
        # colliding on the `mentions` unique constraint — the concurrent double-poll the
        # epic recorded as this story's to close.
        #
        # Partial, on the pending statuses only, because finished runs are the history and
        # a title accumulates thousands of them. The index is therefore also the reason a
        # finished run must be committed *before* its successor is queued: while a run is
        # still `RUNNING` it occupies its title's slot.
        Index(
            "uq_collection_run_one_pending_per_title",
            "title_id",
            unique=True,
            postgresql_where=_ONE_PENDING_RUN_PREDICATE,
            sqlite_where=_ONE_PENDING_RUN_PREDICATE,
        ),
    )

    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[CollectionRunStatus] = mapped_column(
        SqlEnum(CollectionRunStatus, name="collection_run_status", native_enum=False),
        nullable=False,
        default=CollectionRunStatus.QUEUED,
    )
    trigger: Mapped[CollectionRunTrigger] = mapped_column(
        SqlEnum(CollectionRunTrigger, name="collection_run_trigger", native_enum=False),
        nullable=False,
    )

    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The cadence this cycle was scheduled at, as it stood when it was queued.
    polls_per_day: Mapped[int] = mapped_column(Integer, nullable=False)

    # What the cycle did. Every one of these is a count of items, not of provider calls;
    # `pages_fetched` is the count that maps to spend.
    variants_planned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mentions_stored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mentions_already_known: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unreadable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    failure_reason: Mapped[str | None] = mapped_column(
        String(FAILURE_REASON_MAX_LENGTH), nullable=True
    )

    title: Mapped[Title] = relationship(lazy="raise")

    @property
    def is_claimable(self) -> bool:
        return self.status is CollectionRunStatus.QUEUED

    def __repr__(self) -> str:
        return f"<CollectionRun {self.status} title={self.title_id} due={self.scheduled_for}>"

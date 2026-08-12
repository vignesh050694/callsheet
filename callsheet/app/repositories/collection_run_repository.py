"""Data access for the polling queue. Queries only — the cadence and the rules are above."""

import uuid
from collections.abc import Sequence
from datetime import datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_run import CollectionRun, CollectionRunStatus

_logger = structlog.get_logger(__name__)

_PENDING_STATUSES = (CollectionRunStatus.QUEUED, CollectionRunStatus.RUNNING)


class CollectionRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, run: CollectionRun) -> None:
        self._session.add(run)

    async def claim_due(self, now: datetime, *, limit: int) -> list[CollectionRun]:
        """Takes ownership of up to `limit` due cycles, moving them out of the queue.

        `SKIP LOCKED` is what makes more than one worker safe: two workers selecting due
        rows at the same moment would otherwise both read the same queued run, both mark it
        running, and both poll — paying twice for one cycle and colliding on the `mentions`
        unique constraint while they do it. With it, the second worker steps over rows the
        first has already taken and claims the next ones instead.

        SQLite renders no locking clause at all, so under the test suite this degrades to a
        plain select. That is sound there — the suite has one connection — but it does mean
        concurrency itself is a property of the deployment database, not something the
        tests can demonstrate.

        The claim is only durable once the caller commits, which it must do *before*
        starting the work. Holding the transaction open across a minutes-long poll would
        keep the row locked for its whole duration and turn a crashed worker into a stuck
        queue.
        """
        statement = (
            select(CollectionRun)
            .where(
                CollectionRun.status == CollectionRunStatus.QUEUED,
                CollectionRun.scheduled_for <= now,
            )
            .order_by(CollectionRun.scheduled_for, CollectionRun.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(statement)
        runs = list(result.scalars().all())

        for run in runs:
            run.status = CollectionRunStatus.RUNNING
            run.started_at = now
        await self._session.flush()

        _logger.debug("collection.run.claimed", claimed=len(runs), limit=limit)
        return runs

    async def get_by_id(self, run_id: uuid.UUID) -> CollectionRun | None:
        result = await self._session.execute(
            select(CollectionRun).where(CollectionRun.id == run_id)
        )
        return result.scalars().first()

    async def has_pending_for_title(self, title_id: uuid.UUID) -> bool:
        """Whether this title already has a cycle owed to it.

        The guard against a title accumulating a queue. A run is enqueued when a title is
        created and again as each cycle finishes; anything that enqueues out of band — an
        operator, a retry — must not add a second cycle on top of one already waiting, or
        the title silently polls at twice its configured rate and costs twice as much.
        """
        result = await self._session.execute(
            select(CollectionRun.id)
            .where(
                CollectionRun.title_id == title_id,
                CollectionRun.status.in_(_PENDING_STATUSES),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def next_pending_for_title(self, title_id: uuid.UUID) -> CollectionRun | None:
        """The cycle this title is waiting on, if any — soonest first."""
        result = await self._session.execute(
            select(CollectionRun)
            .where(
                CollectionRun.title_id == title_id,
                CollectionRun.status.in_(_PENDING_STATUSES),
            )
            .order_by(CollectionRun.scheduled_for, CollectionRun.id)
            .limit(1)
        )
        return result.scalars().first()

    async def latest_finished_for_title(self, title_id: uuid.UUID) -> CollectionRun | None:
        """The most recently completed cycle, whatever its outcome.

        Ordered by `finished_at` rather than `scheduled_for`, because "when did this title
        last actually collect" is a question about what happened, and a late run finishing
        after a punctual one would answer it wrongly under the other ordering.
        """
        result = await self._session.execute(
            select(CollectionRun)
            .where(
                CollectionRun.title_id == title_id,
                CollectionRun.finished_at.is_not(None),
            )
            .order_by(CollectionRun.finished_at.desc(), CollectionRun.id)
            .limit(1)
        )
        return result.scalars().first()

    async def list_for_title(
        self, title_id: uuid.UUID, *, limit: int
    ) -> Sequence[CollectionRun]:
        result = await self._session.execute(
            select(CollectionRun)
            .where(CollectionRun.title_id == title_id)
            .order_by(CollectionRun.scheduled_for.desc(), CollectionRun.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_finished_for_title(self, title_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(CollectionRun)
            .where(
                CollectionRun.title_id == title_id,
                CollectionRun.finished_at.is_not(None),
            )
        )
        return int(result.scalar_one())

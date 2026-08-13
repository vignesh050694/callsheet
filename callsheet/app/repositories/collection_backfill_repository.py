"""Data access for backfill requests. Queries only — no business rules."""

import uuid
from datetime import datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_backfill import CollectionBackfill, CollectionBackfillStatus

_logger = structlog.get_logger(__name__)

_PENDING_STATUSES = (CollectionBackfillStatus.QUEUED, CollectionBackfillStatus.RUNNING)


class CollectionBackfillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, backfill: CollectionBackfill) -> CollectionBackfill:
        self._session.add(backfill)
        return backfill

    async def get_by_id(self, backfill_id: uuid.UUID) -> CollectionBackfill | None:
        return await self._session.get(CollectionBackfill, backfill_id)

    async def has_pending_for_title(self, title_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            select(CollectionBackfill.id)
            .where(
                CollectionBackfill.title_id == title_id,
                CollectionBackfill.status.in_(_PENDING_STATUSES),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_for_title(
        self, title_id: uuid.UUID, *, limit: int, offset: int = 0
    ) -> list[CollectionBackfill]:
        """Newest request first — the one a studio just made is the one they are watching."""
        result = await self._session.execute(
            select(CollectionBackfill)
            .where(CollectionBackfill.title_id == title_id)
            .order_by(CollectionBackfill.created_at.desc(), CollectionBackfill.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_for_title(self, title_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(CollectionBackfill)
            .where(CollectionBackfill.title_id == title_id)
        )
        return int(result.scalar_one())

    async def claim_queued(self, claimed_at: datetime, *, limit: int) -> list[CollectionBackfill]:
        """Takes queued backfills and marks them running, so no other worker takes them.

        `SKIP LOCKED` for the same reason `claim_due` uses it, and with more at stake: two
        workers taking the same backfill would pay the whole quote twice. SQLite renders no
        locking clause, which is sound under a single-connection test suite and means
        concurrency here is a property of the deployment database rather than of the tests.

        Oldest first. A studio who asked an hour ago is ahead of one who asked a minute ago,
        and a backfill nobody claims because newer ones keep arriving is a request that
        silently never runs.
        """
        result = await self._session.execute(
            select(CollectionBackfill)
            .where(CollectionBackfill.status == CollectionBackfillStatus.QUEUED)
            .order_by(CollectionBackfill.created_at, CollectionBackfill.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        claimed = list(result.scalars().all())
        for backfill in claimed:
            backfill.status = CollectionBackfillStatus.RUNNING
            backfill.started_at = claimed_at
        await self._session.flush()

        _logger.debug("collection.backfill.claimed", claimed=len(claimed), limit=limit)
        return claimed

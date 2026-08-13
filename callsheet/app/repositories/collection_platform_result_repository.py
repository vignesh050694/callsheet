"""Data access for per-platform collection outcomes. Queries only — no business rules."""

import uuid
from collections.abc import Sequence
from datetime import datetime

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.platforms import Platform
from app.models.collection_platform_result import (
    CollectionPlatformResult,
    PlatformCollectionStatus,
)

_logger = structlog.get_logger(__name__)


class CollectionPlatformResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_all(self, results: Sequence[CollectionPlatformResult]) -> None:
        if results:
            self._session.add_all(list(results))
            _logger.debug("collection.platform_result.add_all", results=len(results))

    async def last_success_at_by_platform(
        self, title_id: uuid.UUID
    ) -> dict[Platform, datetime]:
        """When each platform last collected successfully for this title.

        One grouped query rather than one per platform: the dashboard header asks about
        every configured platform at once, and four round trips per title on a list of
        twenty titles is eighty queries to render one screen.
        """
        result = await self._session.execute(
            select(
                CollectionPlatformResult.platform,
                func.max(CollectionPlatformResult.finished_at),
            )
            .where(
                CollectionPlatformResult.title_id == title_id,
                CollectionPlatformResult.status == PlatformCollectionStatus.SUCCEEDED,
            )
            .group_by(CollectionPlatformResult.platform)
        )
        return {platform: finished_at for platform, finished_at in result.all()}

    async def attempted_platforms(self, title_id: uuid.UUID) -> set[Platform]:
        """Every platform this title has ever tried, whatever came of it.

        The read that separates "not started yet" from "tried and never worked" — two states
        that both have no successful collection and need opposite things said about them.
        """
        result = await self._session.execute(
            select(CollectionPlatformResult.platform)
            .where(CollectionPlatformResult.title_id == title_id)
            .distinct()
        )
        return set(result.scalars().all())

    async def recent_for_platform(
        self, title_id: uuid.UUID, platform: Platform, *, limit: int
    ) -> list[CollectionPlatformResult]:
        """This platform's last few attempts, newest first.

        Ordered by `finished_at` rather than `created_at`: `created_at` is a server default,
        and neither Postgres's transaction-start `now()` nor SQLite's whole-second
        `CURRENT_TIMESTAMP` orders attempts that land inside the same tick.
        """
        result = await self._session.execute(
            select(CollectionPlatformResult)
            .where(
                CollectionPlatformResult.title_id == title_id,
                CollectionPlatformResult.platform == platform,
            )
            .order_by(desc(CollectionPlatformResult.finished_at), CollectionPlatformResult.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def consecutive_failures(
        self, title_id: uuid.UUID, platform: Platform, *, window: int
    ) -> int:
        """How many attempts in a row this platform has failed, most recent first.

        Bounded by `window` rather than walking the whole history, because the only question
        anyone asks of this number is whether it has crossed a threshold — and a platform
        that has been broken for a month would otherwise mean reading a month of rows to
        rediscover that it is still broken.
        """
        recent = await self.recent_for_platform(title_id, platform, limit=window)
        failures = 0
        for attempt in recent:
            if attempt.status.is_reporting:
                break
            failures += 1
        return failures

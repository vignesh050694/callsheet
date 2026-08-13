"""Data access for versioned analysis rows. Queries only — no business rules."""

import uuid
from collections.abc import Sequence
from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mention_analysis import MentionAnalysis

_logger = structlog.get_logger(__name__)


class MentionAnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def analyzed_mention_ids(
        self,
        pipeline_version: str,
        mention_ids: Sequence[uuid.UUID],
    ) -> set[uuid.UUID]:
        """Which of these mentions this version has already judged.

        Asked for the whole batch at once so a resumed reprocess skips finished work
        without a query per mention — a six-week corpus is the case this story is written
        against, and a reprocess that cannot resume is one nobody will dare start.
        """
        if not mention_ids:
            return set()
        result = await self._session.execute(
            select(MentionAnalysis.mention_id).where(
                MentionAnalysis.pipeline_version == pipeline_version,
                MentionAnalysis.mention_id.in_(mention_ids),
            )
        )
        return set(result.scalars().all())

    async def add_all(self, analyses: Sequence[MentionAnalysis]) -> None:
        if not analyses:
            return
        self._session.add_all(list(analyses))
        await self._session.flush()
        _logger.debug("mention_analysis.query.add_all", count=len(analyses))

    async def count_for_title(self, title_id: uuid.UUID, pipeline_version: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(MentionAnalysis)
            .where(
                MentionAnalysis.title_id == title_id,
                MentionAnalysis.pipeline_version == pipeline_version,
            )
        )
        return int(result.scalar_one())

    async def list_for_title(
        self,
        title_id: uuid.UUID,
        pipeline_version: str,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[MentionAnalysis]:
        result = await self._session.execute(
            select(MentionAnalysis)
            .where(
                MentionAnalysis.title_id == title_id,
                MentionAnalysis.pipeline_version == pipeline_version,
            )
            .order_by(MentionAnalysis.analyzed_at.desc(), MentionAnalysis.mention_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def pipeline_versions_for_title(self, title_id: uuid.UUID) -> list[str]:
        """Every version that has judged this title, so a reader can choose one."""
        result = await self._session.execute(
            select(MentionAnalysis.pipeline_version)
            .where(MentionAnalysis.title_id == title_id)
            .group_by(MentionAnalysis.pipeline_version)
            .order_by(MentionAnalysis.pipeline_version)
        )
        return list(result.scalars().all())

    async def delete_for_title_and_version(
        self, title_id: uuid.UUID, pipeline_version: str
    ) -> int:
        """Discards one version's verdicts. Never touches mentions or raw payloads.

        The undo for a bad model run: the corpus is untouched, so the same version can be
        recomputed afterwards without spending anything.
        """
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                delete(MentionAnalysis).where(
                    MentionAnalysis.title_id == title_id,
                    MentionAnalysis.pipeline_version == pipeline_version,
                )
            ),
        )
        return int(result.rowcount or 0)

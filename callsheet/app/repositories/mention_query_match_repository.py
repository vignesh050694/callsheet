"""Data access for query-variant attribution. Queries only."""

import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mention_query_match import MentionQueryMatch

_logger = structlog.get_logger(__name__)


class MentionQueryMatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def existing_pairs(
        self, mention_ids: Sequence[uuid.UUID], query_variant: str
    ) -> set[uuid.UUID]:
        """Which of these mentions this variant has already been credited with.

        Asked for the whole batch in one query rather than per mention: polls overlap by
        design, so on a steady campaign most of what a variant returns it has returned
        before, and a per-item round trip would dominate the cycle.
        """
        if not mention_ids:
            return set()
        result = await self._session.execute(
            select(MentionQueryMatch.mention_id).where(
                MentionQueryMatch.mention_id.in_(mention_ids),
                MentionQueryMatch.query_variant == query_variant,
            )
        )
        return set(result.scalars().all())

    def add_all(self, matches: Sequence[MentionQueryMatch]) -> None:
        if not matches:
            return
        self._session.add_all(matches)
        _logger.debug("mention_query_match.query.add_all", matches=len(matches))

    async def variants_for_mention(self, mention_id: uuid.UUID) -> list[str]:
        """Every variant that has found this post, in a stable order."""
        result = await self._session.execute(
            select(MentionQueryMatch.query_variant)
            .where(MentionQueryMatch.mention_id == mention_id)
            .order_by(MentionQueryMatch.first_matched_at, MentionQueryMatch.query_variant)
        )
        return list(result.scalars().all())

    async def mention_counts_by_variant(self, title_id: uuid.UUID) -> dict[str, int]:
        """How many distinct posts each variant has found for this title.

        The attribution read: which of the studio's terms are earning their cost, and which
        alias is worth suggesting they add (E02-S04). Counts posts, not matches, which are
        the same thing here only because the unique constraint makes them so.
        """
        result = await self._session.execute(
            select(
                MentionQueryMatch.query_variant,
                func.count(func.distinct(MentionQueryMatch.mention_id)),
            )
            .where(MentionQueryMatch.title_id == title_id)
            .group_by(MentionQueryMatch.query_variant)
            .order_by(MentionQueryMatch.query_variant)
        )
        return {variant: int(count) for variant, count in result.all()}

    async def count_for_title(self, title_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(MentionQueryMatch)
            .where(MentionQueryMatch.title_id == title_id)
        )
        return int(result.scalar_one())

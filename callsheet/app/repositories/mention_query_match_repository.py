"""Data access for query-variant attribution. Queries only."""

import uuid
from collections.abc import Sequence
from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mention_query_match import MatchSource, MentionQueryMatch

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

    async def promote_retroactive_to_collection(
        self, mention_ids: Sequence[uuid.UUID], query_variant: str
    ) -> int:
        """Upgrades credit a term was given on paper to credit it has now actually earned.

        A term approved from the suggestion list (E02-S04) is credited against posts
        already in the corpus before it has ever run as a query. When the next cycle does
        run it and the provider returns one of those same posts, the term has genuinely
        earned that hit — but the row already exists, so `existing_pairs` reports the pair
        as credited and no insert happens. Without this the row is stuck as `RETROACTIVE`
        for good, and every read of "which variants are earning their cost" undercounts
        the term for the whole life of the campaign.

        A statement rather than an ORM loop: the rows are not otherwise needed, and the
        cycle already holds the ids. `first_matched_at` is deliberately left alone — see
        the column's own docstring; it records when the variant was first *credited* with
        the post, and the retroactive scan is what established that.
        """
        if not mention_ids:
            return 0
        result = await self._session.execute(
            update(MentionQueryMatch)
            .where(
                MentionQueryMatch.mention_id.in_(mention_ids),
                MentionQueryMatch.query_variant == query_variant,
                MentionQueryMatch.match_source == MatchSource.RETROACTIVE,
            )
            .values(match_source=MatchSource.COLLECTION)
        )
        promoted = cast("CursorResult[Any]", result).rowcount
        if promoted:
            _logger.info(
                "mention_query_match.promoted_to_collection",
                query_variant=query_variant,
                promoted=promoted,
            )
        return promoted

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

    async def mention_counts_by_variant(
        self, title_id: uuid.UUID, *, source: MatchSource | None = None
    ) -> dict[str, int]:
        """How many distinct posts each variant has found for this title.

        The attribution read: which of the studio's terms are earning their cost, and which
        alias is worth suggesting they add (E02-S04). Counts posts, not matches, which are
        the same thing here only because the unique constraint makes them so.

        `source` narrows it to one kind of credit. "Which variants are earning their cost"
        must pass `MatchSource.COLLECTION`, because a retroactively matched post was never
        fetched by that query and crediting it would report a term as pulling its weight
        before it has run once. Left unset, this counts both — the honest answer to the
        different question "how much of the corpus does this term account for".
        """
        statement = select(
            MentionQueryMatch.query_variant,
            func.count(func.distinct(MentionQueryMatch.mention_id)),
        ).where(MentionQueryMatch.title_id == title_id)
        if source is not None:
            statement = statement.where(MentionQueryMatch.match_source == source)
        result = await self._session.execute(
            statement.group_by(MentionQueryMatch.query_variant).order_by(
                MentionQueryMatch.query_variant
            )
        )
        return {variant: int(count) for variant, count in result.all()}

    async def count_for_title(self, title_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(MentionQueryMatch)
            .where(MentionQueryMatch.title_id == title_id)
        )
        return int(result.scalar_one())

"""Data access for mentions and their raw payloads. Queries only — no business rules."""

import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.platforms import Platform
from app.models.mention import Mention, MentionRawPayload

_logger = structlog.get_logger(__name__)


class MentionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def existing_external_ids(
        self,
        title_id: uuid.UUID,
        platform: Platform,
        external_ids: Sequence[str],
    ) -> set[str]:
        """Which of these posts this title already holds.

        Asked as one query for the whole page rather than one per item: a poll re-reads
        the most recent posts every time it runs, so on a steady campaign most of a page
        is already known and a per-item round trip would dominate the run.
        """
        if not external_ids:
            return set()
        result = await self._session.execute(
            select(Mention.external_id).where(
                Mention.title_id == title_id,
                Mention.platform == platform,
                Mention.external_id.in_(external_ids),
            )
        )
        return set(result.scalars().all())

    async def existing_payload_external_ids(
        self,
        title_id: uuid.UUID,
        platform: Platform,
        external_ids: Sequence[str],
    ) -> set[str]:
        """Which posts already have a stored payload, readable or not.

        Separate from `existing_external_ids` because the two can disagree: an item that
        failed to normalise has a payload and no mention, and re-collecting it must not
        insert a second payload row.
        """
        if not external_ids:
            return set()
        result = await self._session.execute(
            select(MentionRawPayload.external_id).where(
                MentionRawPayload.title_id == title_id,
                MentionRawPayload.platform == platform,
                MentionRawPayload.external_id.in_(external_ids),
            )
        )
        return {external_id for external_id in result.scalars().all() if external_id}

    async def add_all(
        self,
        mentions: Sequence[Mention],
        payloads: Sequence[MentionRawPayload],
    ) -> None:
        """Writes both forms in one flush, so a payload is never stored without its mention.

        Mentions are flushed first because each payload's `mention_id` is only assigned
        once its mention has an id.
        """
        if mentions:
            self._session.add_all(mentions)
            await self._session.flush()
        if payloads:
            self._session.add_all(payloads)
            await self._session.flush()
        _logger.debug(
            "mention.query.add_all", mentions=len(mentions), payloads=len(payloads)
        )

    async def list_for_title(
        self,
        title_id: uuid.UUID,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[Mention]:
        """Newest first, and never filtered by provider — there is no provider to filter on."""
        result = await self._session.execute(
            select(Mention)
            .where(Mention.title_id == title_id)
            .order_by(Mention.posted_at.desc(), Mention.external_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_payload_for_mention(self, mention_id: uuid.UUID) -> MentionRawPayload | None:
        result = await self._session.execute(
            select(MentionRawPayload).where(MentionRawPayload.mention_id == mention_id)
        )
        return result.scalar_one_or_none()

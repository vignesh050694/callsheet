"""Data access for mentions and their raw payloads. Queries only — no business rules."""

import uuid
from collections.abc import Sequence
from datetime import datetime

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

    async def list_for_title_in_window(
        self,
        title_id: uuid.UUID,
        *,
        posted_from: datetime | None = None,
        posted_until: datetime | None = None,
        limit: int,
        after_id: uuid.UUID | None = None,
    ) -> list[Mention]:
        """A page of one title's corpus within a date window, paged by primary key.

        Keyset-paged rather than OFFSET-paged, because a reprocess walks a six-week
        corpus in batches while collection keeps inserting into it, and an OFFSET walk
        over a table growing underneath it skips rows.

        Ordered by `id` and not by `posted_at`, even though `posted_at` is the axis the
        window filters on and chronological order would read more naturally. The reason is
        that a reprocess *rewrites* `posted_at` when it repairs a mention from its stored
        payload — correcting a timestamp is one of the things it exists to do. Paging by a
        column the walk itself mutates means a repaired row can jump across the cursor:
        forward, and it gets visited a second time; backward, and every row between the
        old and new position is skipped with no error and no count. `id` is assigned once
        and never changes, so the walk stays a total order no matter what the walk does to
        the rows it has already passed.
        """
        statement = select(Mention).where(Mention.title_id == title_id)
        if posted_from is not None:
            statement = statement.where(Mention.posted_at >= posted_from)
        if posted_until is not None:
            statement = statement.where(Mention.posted_at <= posted_until)
        if after_id is not None:
            statement = statement.where(Mention.id > after_id)
        result = await self._session.execute(
            statement.order_by(Mention.id).limit(limit)
        )
        return list(result.scalars().all())

    async def payloads_for_mentions(
        self, mention_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, MentionRawPayload]:
        """The stored payloads behind these mentions, keyed by mention id.

        The read a reprocess runs on: it re-derives from what was paid for, never from the
        normalised row, so a mapping that was wrong when the post arrived can be corrected
        without another call.
        """
        if not mention_ids:
            return {}
        result = await self._session.execute(
            select(MentionRawPayload).where(MentionRawPayload.mention_id.in_(mention_ids))
        )
        return {
            payload.mention_id: payload
            for payload in result.scalars().all()
            if payload.mention_id is not None
        }

    async def get_payload_for_mention(self, mention_id: uuid.UUID) -> MentionRawPayload | None:
        result = await self._session.execute(
            select(MentionRawPayload).where(MentionRawPayload.mention_id == mention_id)
        )
        return result.scalar_one_or_none()

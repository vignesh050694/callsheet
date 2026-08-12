"""Data access for mentions and their raw payloads. Queries only — no business rules."""

import uuid
from collections.abc import Sequence
from datetime import datetime

import structlog
from sqlalchemy import and_, func, or_, select
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
        after_collected_at: datetime | None = None,
        after_id: uuid.UUID | None = None,
    ) -> list[Mention]:
        """A page of one title's corpus within a date window, paged by arrival order.

        Keyset-paged rather than OFFSET-paged, because a reprocess walks a six-week
        corpus in batches while collection keeps inserting into it, and an OFFSET walk
        over a table growing underneath it skips rows.

        Two things decide the ordering, and each one rules out an obvious alternative.

        **Not `posted_at`**, even though that is the axis the window filters on and
        chronological order would read more naturally, because a reprocess *rewrites*
        `posted_at` when it repairs a mention from its stored payload — correcting a
        timestamp is one of the things it exists to do. Paging by a column the walk itself
        mutates lets a repaired row jump across the cursor: forward, and it is visited
        twice; backward, and every row between its old and new position is skipped with no
        error and no count. Both were observed (E03-S04).

        **Not `id` alone**, which is immutable and was what this walked by first, but is a
        random UUIDv4 and therefore carries no order at all. A mention inserted by a
        concurrent poll sorts uniformly at random relative to the cursor, so roughly half
        of everything collected during a long walk fell behind it and was never seen by
        that run. That was theoretical until E03-S01 put a scheduler in the product; it is
        not any more.

        **Not `created_at`**, the obvious arrival column, because it is a *server* default.
        Postgres `now()` is transaction-start time, so a page whose transaction began
        before the cursor reached its timestamp still lands behind it; and SQLite's
        `CURRENT_TIMESTAMP` has one-second resolution and no fractional part at all, so the
        stored text never matches a bound Python datetime and the walk stops after its
        first batch. Both were observed.

        `collected_at` is set by the application at the moment the page was fetched, with
        microsecond precision and the same format in every database. It is written once and
        no code path updates it — a reprocess rewrites what the post *says*, never when it
        arrived — so `(collected_at, id)` is immutable in both components and ordered by
        arrival in the first.
        """
        statement = select(Mention).where(Mention.title_id == title_id)
        if posted_from is not None:
            statement = statement.where(Mention.posted_at >= posted_from)
        if posted_until is not None:
            statement = statement.where(Mention.posted_at <= posted_until)
        if after_collected_at is not None and after_id is not None:
            # Written out rather than as a row comparison: SQLAlchemy does not compile a
            # Python tuple comparison on ORM columns into the SQL row constructor, so
            # `(a, b) > (x, y)` silently becomes something else entirely.
            statement = statement.where(
                or_(
                    Mention.collected_at > after_collected_at,
                    and_(
                        Mention.collected_at == after_collected_at,
                        Mention.id > after_id,
                    ),
                )
            )
        result = await self._session.execute(
            statement.order_by(Mention.collected_at, Mention.id).limit(limit)
        )
        return list(result.scalars().all())

    async def ids_by_external_id(
        self,
        title_id: uuid.UUID,
        platform: Platform,
        external_ids: Sequence[str],
    ) -> dict[str, uuid.UUID]:
        """Maps this title's post ids to mention ids, for attributing a query variant.

        The read behind "which mention did this variant just find". It has to cover posts
        the cycle did *not* store as well as the ones it did: a popular post is stored by
        the first variant that returns it and is already known to the next three, and those
        three earned their credit just as much as the first.
        """
        if not external_ids:
            return {}
        result = await self._session.execute(
            select(Mention.external_id, Mention.id).where(
                Mention.title_id == title_id,
                Mention.platform == platform,
                Mention.external_id.in_(external_ids),
            )
        )
        return {external_id: mention_id for external_id, mention_id in result.all()}

    async def count_for_title(self, title_id: uuid.UUID) -> int:
        """How many posts this title holds. Unsegmented — account typing is E04-S03."""
        result = await self._session.execute(
            select(func.count()).select_from(Mention).where(Mention.title_id == title_id)
        )
        return int(result.scalar_one())

    async def latest_posted_at_for_title(self, title_id: uuid.UUID) -> datetime | None:
        result = await self._session.execute(
            select(func.max(Mention.posted_at)).where(Mention.title_id == title_id)
        )
        return result.scalar_one_or_none()

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

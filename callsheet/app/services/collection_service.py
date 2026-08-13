"""Collecting one page for a title, and storing both forms of it (E03-S07).

This is the layer the pipeline calls. It names a platform and a query; it never names a
provider, an endpoint, or a vendor field. Swapping the endpoint behind a platform changes
what this service logs and nothing about what it does.

It does not decide *when* to collect or *what* to ask for — cadence is E03-S02, the first
run is E03-S01, and the query comes from the title's identity set. It decides only that a
page is fetched once, stored once, and never silently discarded.
"""

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.platforms import Platform
from app.core.timestamps import as_utc
from app.models.mention import Mention, MentionRawPayload
from app.repositories.mention_repository import MentionRepository
from app.services.collection.mention_shape import NormalizedMention
from app.services.collection.source import (
    CollectedItem,
    CollectionPage,
    CollectionSource,
    CollectionWindow,
)

_logger = structlog.get_logger(__name__)

# The error column is bounded; a provider's exception text is not.
_MAX_STORED_ERROR_LENGTH = 500


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """What one page did, in the terms collection health will later report on (E03-S05)."""

    platform: Platform
    endpoint_key: str
    provider: str
    fetched: int
    stored: int
    already_known: int
    unreadable: int
    next_page: str | None
    # Every identifiable post this page returned, new and already-held alike. The caller
    # needs both to credit the query variant that fetched them (E03-S01): a popular post
    # is stored by the first variant that finds it and is "already known" to the next
    # three, and those three found it just as genuinely as the first did.
    seen_external_ids: tuple[str, ...] = ()
    # The oldest post on the page, over everything readable on it rather than over what was
    # stored. A backfill (E03-S03) reports the depth it actually reached, and depth is a
    # property of what the provider was willing to return — a page of posts this title
    # already holds proves the search got that far back just as well as a page of new ones.
    earliest_posted_at: datetime | None = None


class CollectionService:
    def __init__(self, session: AsyncSession, source: CollectionSource) -> None:
        self._session = session
        self._mention_repository = MentionRepository(session)
        self._source = source

    async def collect_page(
        self,
        title_id: uuid.UUID,
        platform: Platform,
        query: str,
        *,
        limit: int,
        page: str | None = None,
        backfill_window: CollectionWindow | None = None,
    ) -> CollectionResult:
        """Fetches one page for this title and stores what is new in it.

        `backfill_window` does two things at once, and they are one parameter rather than
        two on purpose (E03-S03): it bounds the request to a past date range, and it marks
        what that request stores as backfilled. A mention is backfilled exactly when it was
        fetched by a windowed historical call, so the two cannot be set independently and a
        caller cannot mark a live poll's results as history or collect a range without
        saying it did.
        """
        started_at = time.perf_counter()
        fetched_page = await self._source.fetch(
            platform, query, page=page, limit=limit, window=backfill_window
        )
        collected_at = datetime.now(UTC)

        result = await self._store_and_commit(
            title_id, fetched_page, collected_at, is_backfill=backfill_window is not None
        )

        _logger.info(
            "collection.page.completed",
            title_id=str(title_id),
            platform=str(platform),
            endpoint=result.endpoint_key,
            provider=result.provider,
            fetched=result.fetched,
            stored=result.stored,
            already_known=result.already_known,
            unreadable=result.unreadable,
            is_backfill=backfill_window is not None,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
        )
        return result

    async def _store_and_commit(
        self,
        title_id: uuid.UUID,
        page: CollectionPage,
        collected_at: datetime,
        *,
        is_backfill: bool,
    ) -> CollectionResult:
        """Writes the page, retrying once if another poll stored some of it first.

        The retry is what makes a scheduler safe (E03-S01). `_store` decides what is new by
        reading the ids this title already holds, and between that read and the commit
        another cycle polling the same title can insert one of them. The unique constraint
        then rejects the *whole* page — including the posts nobody else had — and a payload
        that has already been paid for is lost.

        A second pass re-reads what is known, so the row that collided is now recognised
        and skipped, and the rest of the page lands. One retry is enough by construction:
        the conflict is only ever "somebody else already stored this post", and after the
        re-read that post is no longer new. A second failure means something other than an
        overlapping poll, and is raised rather than absorbed.

        The retry only narrows the window; it does not close it, and it is not the primary
        defence. Runs are claimed with `SKIP LOCKED` so two workers do not take the same
        cycle, and a title is never queued twice concurrently. This is what remains for the
        cases those cannot cover — a manual run started beside a scheduled one.
        """
        # `expire_on_commit=False` is set on the session factory, so `result` stays
        # readable after the commit below.
        try:
            result = await self._store(title_id, page, collected_at, is_backfill=is_backfill)
            # The service owns the transaction boundary here as everywhere else in this
            # codebase — `get_db_session` rolls back and never commits on its behalf.
            # Without this the whole page, including payloads that have already been paid
            # for, is discarded when the session closes.
            await self._session.commit()
            return result
        except IntegrityError:
            await self._session.rollback()
            _logger.warning(
                "collection.page.write_conflict",
                title_id=str(title_id),
                platform=str(page.platform),
                endpoint=page.endpoint.key,
            )

        result = await self._store(title_id, page, collected_at, is_backfill=is_backfill)
        await self._session.commit()
        _logger.info(
            "collection.page.write_conflict_resolved",
            title_id=str(title_id),
            platform=str(page.platform),
            stored=result.stored,
            already_known=result.already_known,
        )
        return result

    async def _store(
        self,
        title_id: uuid.UUID,
        page: CollectionPage,
        collected_at: datetime,
        *,
        is_backfill: bool,
    ) -> CollectionResult:
        """Writes the page's new items, skipping what this title already holds.

        Idempotent by post rather than by run: polls overlap by design, so the same post
        arrives on consecutive cycles and must not accumulate rows. First capture wins,
        which is the same snapshot-at-collection rule the engagement counts follow.
        """
        known = await self._known_external_ids(title_id, page)
        seen_in_page: set[str] = set()

        mentions: list[Mention] = []
        payloads: list[MentionRawPayload] = []
        already_known = 0
        unreadable = 0

        for item in page.items:
            # Read from the item, not from its mention: an item that failed to normalise
            # still has an id, and it is what stops the same broken payload being stored
            # again on every overlapping poll.
            external_id = item.external_id

            if external_id is not None:
                if external_id in known or external_id in seen_in_page:
                    already_known += 1
                    continue
                seen_in_page.add(external_id)

            mention = self._build_mention(
                title_id, item.mention, collected_at, is_backfill=is_backfill
            )
            if mention is not None:
                mentions.append(mention)
            else:
                unreadable += 1

            payloads.append(
                self._build_payload(title_id, page, item, mention, external_id, collected_at)
            )

        await self._mention_repository.add_all(mentions, payloads)

        return CollectionResult(
            platform=page.platform,
            endpoint_key=page.endpoint.key,
            provider=page.endpoint.provider,
            fetched=len(page.items),
            stored=len(mentions),
            already_known=already_known,
            unreadable=unreadable,
            next_page=page.next_page,
            # Order preserved and deduped, so a provider echoing one post twice in a page
            # credits the variant once.
            seen_external_ids=tuple(dict.fromkeys(self._identifiable_ids(page))),
            earliest_posted_at=self._earliest_posted_at(page),
        )

    @staticmethod
    def _identifiable_ids(page: CollectionPage) -> list[str]:
        return [item.external_id for item in page.items if item.external_id is not None]

    @staticmethod
    def _earliest_posted_at(page: CollectionPage) -> datetime | None:
        """How far back this page reached, over everything readable on it.

        Not restricted to what was stored. A backfill's second page is mostly posts the
        title already holds, and those prove the search reached their date exactly as well
        as a new post would — measuring depth by what was *inserted* would report a
        successful deep page as no progress and stop the walk one page in.
        """
        posted = [as_utc(item.mention.posted_at) for item in page.readable_items if item.mention]
        return min(posted) if posted else None

    async def _known_external_ids(self, title_id: uuid.UUID, page: CollectionPage) -> set[str]:
        """Ids this title already holds as a mention or as a stored payload.

        Both are asked, because the two can legitimately disagree: an item that failed to
        normalise has a payload and no mention, and re-collecting it must be recognised by
        the payload alone.
        """
        external_ids = self._identifiable_ids(page)
        if not external_ids:
            return set()

        stored_mentions = await self._mention_repository.existing_external_ids(
            title_id, page.platform, external_ids
        )
        stored_payloads = await self._mention_repository.existing_payload_external_ids(
            title_id, page.platform, external_ids
        )
        return stored_mentions | stored_payloads

    @staticmethod
    def _build_mention(
        title_id: uuid.UUID,
        normalized: NormalizedMention | None,
        collected_at: datetime,
        *,
        is_backfill: bool,
    ) -> Mention | None:
        if normalized is None:
            return None
        return Mention(
            is_backfilled=is_backfill,
            title_id=title_id,
            platform=normalized.platform,
            external_id=normalized.external_id,
            permalink=normalized.permalink,
            author_handle=normalized.author_handle,
            author_display_name=normalized.author_display_name,
            author_follower_count=normalized.author_follower_count,
            text=normalized.text,
            posted_at=normalized.posted_at,
            platform_reported_language=normalized.platform_reported_language,
            hashtags=list(normalized.hashtags),
            like_count=normalized.engagement.like_count,
            reply_count=normalized.engagement.reply_count,
            repost_count=normalized.engagement.repost_count,
            quote_count=normalized.engagement.quote_count,
            view_count=normalized.engagement.view_count,
            bookmark_count=normalized.engagement.bookmark_count,
            collected_at=collected_at,
        )

    @staticmethod
    def _build_payload(
        title_id: uuid.UUID,
        page: CollectionPage,
        item: CollectedItem,
        mention: Mention | None,
        external_id: str | None,
        collected_at: datetime,
    ) -> MentionRawPayload:
        """The paid-for artefact, kept whether or not it could be read."""
        error = item.normalization_error
        return MentionRawPayload(
            title_id=title_id,
            mention=mention,
            platform=page.platform,
            external_id=external_id,
            provider=page.endpoint.provider,
            endpoint_key=page.endpoint.key,
            adapter_version=page.adapter_version,
            payload=dict(item.raw_payload),
            normalization_error=error[:_MAX_STORED_ERROR_LENGTH] if error else None,
            collected_at=collected_at,
        )

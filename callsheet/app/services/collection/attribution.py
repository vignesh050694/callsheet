"""Recording which query variant found which post (E03-S01, reused by E03-S03).

Deduplication is what makes the corpus correct and it is also what destroys the more
interesting half of a fan-out: once a post exists, the three other variants that returned it
leave no trace. `mention_query_matches` is that trace, and this is the one place it is
written.

Extracted from `CollectionRunService` when backfill arrived, because a historical page is a
fan-out too. A backfilled post found by a regional alias has to credit that alias or alias
discovery (E02-S04) reads the weeks before signup as weeks in which no alias worked — which
is the opposite of what a backfill is for.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.platforms import Platform
from app.models.mention_query_match import MentionQueryMatch
from app.repositories.mention_query_match_repository import MentionQueryMatchRepository
from app.repositories.mention_repository import MentionRepository
from app.services.collection.query_plan import QueryVariant

_logger = structlog.get_logger(__name__)


class MentionAttributionWriter:
    """Credits a variant with the posts it returned, without double-counting."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._mention_repository = MentionRepository(session)
        self._match_repository = MentionQueryMatchRepository(session)

    async def credit(
        self,
        title_id: uuid.UUID,
        platform: Platform,
        variant: QueryVariant,
        external_ids: tuple[str, ...],
    ) -> int:
        """Records that this variant returned these posts. Returns how many were new.

        Runs over every id the page returned, not only the ones just stored. The scenario
        this is written around is one post matching three variants inside a single cycle:
        the first stores it, the other two see it as already known, and all three found it.
        Crediting only new rows would attribute a popular post entirely to whichever query
        happened to run first.
        """
        if not external_ids:
            return 0

        mention_ids = await self._mention_repository.ids_by_external_id(
            title_id, platform, external_ids
        )
        if not mention_ids:
            # Everything on this page failed to normalise, so there is no mention to hang
            # attribution off. The payloads are stored and a reprocess can recover them
            # (E03-S04), but the variant that found them cannot be recorded until then.
            return 0

        already_credited = await self._match_repository.existing_pairs(
            list(mention_ids.values()), variant.key
        )
        matched_at = datetime.now(UTC)
        matches = [
            MentionQueryMatch(
                title_id=title_id,
                mention_id=mention_id,
                platform=platform,
                query_variant=variant.key,
                first_matched_at=matched_at,
            )
            for mention_id in mention_ids.values()
            if mention_id not in already_credited
        ]
        self._match_repository.add_all(matches)
        await self._session.commit()
        _logger.debug(
            "collection.attribution.credited",
            title_id=str(title_id),
            platform=str(platform),
            variant=variant.key,
            credited=len(matches),
        )
        return len(matches)

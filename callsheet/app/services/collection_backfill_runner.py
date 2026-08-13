"""Executing a backfill: paginate back through a date range, then say how far you got.

The other half of E03-S03. Where `CollectionBackfillService` takes the request and quotes
it, this runs it in the worker — the same process, and the same tick, that runs scheduled
cycles, because a studio who confirms a backfill must not also have to ask someone to start
it.

Three things make this different from a cycle, and each one is a constraint rather than a
preference.

**It paginates, and a cycle does not.** A poll takes the newest page and stops; six weeks of
history is only reachable by walking. That walk is the entire cost of this feature, which is
why it is bounded in three independent ways: the configured page cap, the provider running
out of pages, and the range being covered — whichever comes first.

**It reports depth rather than success.** Platform search endpoints return what they choose
to. A backfill that asked for six weeks and reached eleven days did not fail; it hit the
limit of what X will serve, and the honest answer is the eleven days, stated. Reporting the
*request* back as though it were the result is what concept note §6.4 rules out, and it is
the specific thing this story's Notes insist on.

**A page it fetched is a page it paid for.** Every page is stored before the next is asked
for, so a walk that dies four pages in keeps four pages of corpus rather than throwing away
what has already been bought.
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.collection_endpoints import get_endpoint
from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.core.platforms import Platform
from app.core.timestamps import as_utc
from app.models.collection_backfill import (
    FAILURE_REASON_MAX_LENGTH,
    CollectionBackfill,
    CollectionBackfillStatus,
)
from app.models.title import Title
from app.repositories.collection_backfill_repository import CollectionBackfillRepository
from app.repositories.title_repository import TitleRepository
from app.services.collection.attribution import MentionAttributionWriter
from app.services.collection.backfill_cost import charged_cost_for_page
from app.services.collection.query_plan import QueryVariant, build_query_variants
from app.services.collection.source import CollectionWindow
from app.services.collection.spend_policy import SpendPolicy
from app.services.collection_service import CollectionResult, CollectionService

_logger = structlog.get_logger(__name__)

TITLE_GONE_REASON = "the title was deleted before its backfill ran"
NO_VARIANTS_REASON = "the title's identity set produced no query to run"
ABANDONED_REASON = "the backfill's own completion path failed; closed so it can be asked for again"


@dataclass
class _BackfillTotals:
    """What a backfill accumulated, across every variant and platform in it."""

    pages_fetched: int = 0
    mentions_stored: int = 0
    mentions_already_known: int = 0
    unreadable: int = 0
    charged_cost_usd: float = 0.0
    earliest_posted_at: datetime | None = None
    has_reached_page_cap: bool = False
    platforms_collected: set[Platform] = field(default_factory=set)
    platforms_skipped: dict[Platform, str] = field(default_factory=dict)

    def observe(self, result: CollectionResult) -> None:
        self.pages_fetched += 1
        self.mentions_stored += result.stored
        self.mentions_already_known += result.already_known
        self.unreadable += result.unreadable
        self.charged_cost_usd += _charged_for(result)
        if result.earliest_posted_at is not None and (
            self.earliest_posted_at is None or result.earliest_posted_at < self.earliest_posted_at
        ):
            self.earliest_posted_at = result.earliest_posted_at


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """One finished backfill, in the terms the screen reports it in."""

    backfill_id: uuid.UUID
    title_id: uuid.UUID
    status: CollectionBackfillStatus
    pages_fetched: int
    mentions_stored: int
    mentions_already_known: int
    unreadable: int
    charged_cost_usd: float
    earliest_posted_at: datetime | None
    is_depth_limited: bool
    has_reached_page_cap: bool
    platforms_collected: tuple[Platform, ...]
    platforms_skipped: tuple[Platform, ...]
    failure_reason: str | None


class CollectionBackfillRunner:
    def __init__(
        self,
        session: AsyncSession,
        collection_service: CollectionService,
        spend_policy: SpendPolicy,
        settings: Settings,
    ) -> None:
        self._session = session
        self._backfill_repository = CollectionBackfillRepository(session)
        self._title_repository = TitleRepository(session)
        self._attribution = MentionAttributionWriter(session)
        self._collection_service = collection_service
        self._spend_policy = spend_policy
        self._settings = settings

    async def run_queued_backfills(
        self, *, now: datetime | None = None, limit: int | None = None
    ) -> list[BackfillResult]:
        """Claims queued backfills and runs them one after another.

        The default limit is one per tick, and that is deliberate rather than timid. A
        backfill is the most expensive single action this product takes, and a tick that
        claimed five would hold one worker for however long five walks take while every
        scheduled cycle behind them waited.
        """
        claimed_at = now or datetime.now(UTC)
        batch_size = limit or self._settings.collection_backfill_worker_batch_size

        backfills = await self._backfill_repository.claim_queued(claimed_at, limit=batch_size)
        # Committed before any polling starts, exactly as a claimed cycle is: the claim has
        # to be visible to other workers immediately, and holding this transaction open
        # across a walk would keep the row locked for the walk's whole duration.
        await self._session.commit()

        if not backfills:
            _logger.debug("collection.backfill.nothing_queued")
            return []

        # Ids rather than instances, for the reason `run_due_cycles` learned the hard way: a
        # rollback anywhere in this session expires *every* instance attached to it, so a
        # neighbour's handled failure poisons the ORM objects of backfills that have not
        # started. Reloading inside each iteration re-establishes state rather than merely
        # catching.
        backfill_ids = [backfill.id for backfill in backfills]

        results: list[BackfillResult] = []
        for backfill_id in backfill_ids:
            try:
                backfill = await self._backfill_repository.get_by_id(backfill_id)
                if backfill is None:  # pragma: no cover — claimed moments ago
                    _logger.warning("collection.backfill.vanished", backfill_id=str(backfill_id))
                    continue
                results.append(await self.execute(backfill))
            except Exception:
                _logger.exception("collection.backfill.abandoned", backfill_id=str(backfill_id))
                await self._abandon(backfill_id)
        return results

    async def execute(self, backfill: CollectionBackfill) -> BackfillResult:
        """Runs one claimed backfill to completion, whatever happens inside it."""
        started_at = time.perf_counter()
        backfill_id, title_id = backfill.id, backfill.title_id

        title = await self._title_repository.get_by_id(title_id)
        if title is None:
            return await self._finish(
                backfill, CollectionBackfillStatus.FAILED, TITLE_GONE_REASON, _BackfillTotals()
            )

        totals = _BackfillTotals()
        try:
            status, reason = await self._collect_range(backfill, title, totals)
        except Exception as error:
            # Broad on purpose, and for the same reason a cycle's is: anything that escapes
            # a page — a provider returning nonsense, a dropped connection — must still
            # close this row. A backfill left `RUNNING` occupies its title's only pending
            # slot forever, so the studio can never ask for one again and nothing on any
            # screen says why.
            status, reason = CollectionBackfillStatus.FAILED, f"{type(error).__name__}: {error}"
            _logger.exception(
                "collection.backfill.failed",
                backfill_id=str(backfill_id),
                title_id=str(title_id),
                error_type=type(error).__name__,
            )
            await self._recover_session(backfill)

        result = await self._finish(backfill, status, reason, totals)

        _logger.info(
            "collection.backfill.completed",
            backfill_id=str(backfill_id),
            title_id=str(title_id),
            status=str(status),
            pages=totals.pages_fetched,
            stored=totals.mentions_stored,
            already_known=totals.mentions_already_known,
            unreadable=totals.unreadable,
            charged_cost_usd=round(totals.charged_cost_usd, 4),
            reached_back_to=(
                totals.earliest_posted_at.isoformat() if totals.earliest_posted_at else None
            ),
            is_depth_limited=result.is_depth_limited,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
        )
        return result

    async def _collect_range(
        self, backfill: CollectionBackfill, title: Title, totals: _BackfillTotals
    ) -> tuple[CollectionBackfillStatus, str | None]:
        """Check it may spend, plan it, then walk every platform."""
        decision = await self._spend_policy.decide(title.organization_id)
        if not decision.is_allowed:
            _logger.warning(
                "collection.backfill.refused_by_spend_policy",
                backfill_id=str(backfill.id),
                title_id=str(title.id),
                reason=decision.reason,
            )
            return CollectionBackfillStatus.SKIPPED, decision.reason

        variants = build_query_variants(title, limit=self._settings.collection_variants_per_title)
        if not variants:
            return CollectionBackfillStatus.SKIPPED, NO_VARIANTS_REASON

        window = CollectionWindow(
            posted_from=backfill.requested_from, posted_until=backfill.requested_until
        )
        for platform in self._settings.collection_platforms:
            await self._collect_platform(title, platform, variants, window, backfill, totals)

        return self._verdict(totals)

    async def _collect_platform(
        self,
        title: Title,
        platform: Platform,
        variants: list[QueryVariant],
        window: CollectionWindow,
        backfill: CollectionBackfill,
        totals: _BackfillTotals,
    ) -> None:
        """Every variant walked against one platform, abandoning it on a routing refusal.

        A `ServiceUnavailableError` means the platform is unusable — no endpoint, no
        adapter, no transport — so the remaining variants would raise the identical error
        and charge nothing for it. Recorded once, and this platform is dropped.
        """
        for variant in variants:
            try:
                await self._walk_variant(title, platform, variant, window, backfill, totals)
            except ServiceUnavailableError as error:
                totals.platforms_skipped[platform] = error.message
                _logger.warning(
                    "collection.backfill.platform_unavailable",
                    title_id=str(title.id),
                    platform=str(platform),
                    variant=variant.key,
                    reason=error.message,
                )
                return
        totals.platforms_collected.add(platform)

    async def _walk_variant(
        self,
        title: Title,
        platform: Platform,
        variant: QueryVariant,
        window: CollectionWindow,
        backfill: CollectionBackfill,
        totals: _BackfillTotals,
    ) -> None:
        """Pages one query backwards until it is done, out of pages, or out of budget.

        Three stopping conditions, and they are checked in this order because they cost
        different amounts to be wrong about:

        1. **The range is covered.** Once a page's oldest post is older than
           `requested_from`, everything the studio asked for has been seen and the next page
           would be conversation from before the trailer they are asking about — paid for
           and outside the range.
        2. **The provider is out of pages.** No cursor means no more history is on offer,
           whatever the cap allows. This is the limit the story's Notes are about, and it is
           reached far more often than the cap.
        3. **The page cap.** The product's own ceiling, and the one thing here that is a
           deliberate spending decision rather than a fact about the platform.
        """
        page: str | None = None
        for depth in range(backfill.page_cap):
            result = await self._collection_service.collect_page(
                title.id,
                platform,
                variant.query,
                limit=self._settings.collection_page_size,
                page=page,
                backfill_window=window,
            )
            totals.observe(result)
            await self._attribution.credit(title.id, platform, variant, result.seen_external_ids)

            if self._has_covered_range(result, window):
                return
            page = result.next_page
            if page is None:
                return
            if depth == backfill.page_cap - 1:
                # The walk stopped because of the cap, not because the platform ran out.
                # Worth separating: this one an operator can raise, the other they cannot.
                totals.has_reached_page_cap = True
                _logger.info(
                    "collection.backfill.page_cap_reached",
                    title_id=str(title.id),
                    platform=str(platform),
                    variant=variant.key,
                    page_cap=backfill.page_cap,
                )

    @staticmethod
    def _has_covered_range(result: CollectionResult, window: CollectionWindow) -> bool:
        """Whether this page already reached past the start of the requested range.

        Reads the page's oldest *readable* post. A page on which nothing normalised says
        nothing about depth either way, so the walk continues rather than concluding it is
        finished — stopping there would report a mapping failure as a completed backfill.
        """
        return (
            result.earliest_posted_at is not None
            and result.earliest_posted_at <= window.posted_from
        )

    @staticmethod
    def _verdict(totals: _BackfillTotals) -> tuple[CollectionBackfillStatus, str | None]:
        """Whether a backfill that ran to the end actually collected from anywhere.

        A backfill in which every platform was unusable must not report success: zero
        historical mentions from a working search and zero because nothing was searched look
        identical on a chart, and only one of them is a fact about the film.
        """
        if totals.platforms_collected:
            return CollectionBackfillStatus.SUCCEEDED, None
        if totals.platforms_skipped:
            return CollectionBackfillStatus.SKIPPED, "; ".join(
                f"{platform}: {reason}" for platform, reason in totals.platforms_skipped.items()
            )
        return CollectionBackfillStatus.SKIPPED, "no platform is configured for collection"

    async def _finish(
        self,
        backfill: CollectionBackfill,
        status: CollectionBackfillStatus,
        reason: str | None,
        totals: _BackfillTotals,
    ) -> BackfillResult:
        """Closes the row with what the walk did, and how deep it got."""
        is_depth_limited = self._is_depth_limited(backfill, totals, status)

        backfill.status = status
        backfill.finished_at = datetime.now(UTC)
        backfill.failure_reason = reason[:FAILURE_REASON_MAX_LENGTH] if reason else None
        backfill.pages_fetched = totals.pages_fetched
        backfill.mentions_stored = totals.mentions_stored
        backfill.mentions_already_known = totals.mentions_already_known
        backfill.unreadable = totals.unreadable
        backfill.charged_cost_usd = totals.charged_cost_usd
        backfill.earliest_posted_at = totals.earliest_posted_at
        backfill.is_depth_limited = is_depth_limited
        backfill.has_reached_page_cap = totals.has_reached_page_cap
        await self._session.commit()

        return BackfillResult(
            backfill_id=backfill.id,
            title_id=backfill.title_id,
            status=status,
            pages_fetched=totals.pages_fetched,
            mentions_stored=totals.mentions_stored,
            mentions_already_known=totals.mentions_already_known,
            unreadable=totals.unreadable,
            charged_cost_usd=totals.charged_cost_usd,
            earliest_posted_at=totals.earliest_posted_at,
            is_depth_limited=is_depth_limited,
            has_reached_page_cap=totals.has_reached_page_cap,
            platforms_collected=tuple(sorted(totals.platforms_collected)),
            platforms_skipped=tuple(sorted(totals.platforms_skipped)),
            failure_reason=backfill.failure_reason,
        )

    @staticmethod
    def _is_depth_limited(
        backfill: CollectionBackfill,
        totals: _BackfillTotals,
        status: CollectionBackfillStatus,
    ) -> bool:
        """Whether the walk fell short of the range that was asked for.

        The one computed field on the row, and the only honest way to answer "did I get what
        I asked for". True whenever nothing came back at all, or the oldest post reached is
        still inside the requested range — which means the platform stopped serving history
        before the trailer launch the studio typed in.

        A backfill that never ran is depth-limited by definition; saying otherwise would let
        a skipped one render as complete coverage of a range nobody searched.

        `requested_from` is read back off the row, so it goes through `as_utc`: SQLite
        returns it naive while the depth reached is aware, and comparing the two raises.
        """
        if status is not CollectionBackfillStatus.SUCCEEDED:
            return True
        if totals.earliest_posted_at is None:
            return True
        return totals.earliest_posted_at > as_utc(backfill.requested_from)

    async def _recover_session(self, backfill: CollectionBackfill) -> None:
        """Rolls the failed work back, then makes the row usable again.

        The refresh is not optional. A rollback expires every instance in the session, and
        the next thing this does is write the outcome onto `backfill` — ordinary attribute
        access, which for an expired instance means a query issued from synchronous Python,
        which an async session cannot run. Reloading here, inside `await`, is what lets the
        failure path do its job rather than fail in a second, more confusing way.
        """
        await self._session.rollback()
        await self._session.refresh(backfill)

    async def _abandon(self, backfill_id: uuid.UUID) -> None:
        """Last resort: close a backfill whose own completion path failed.

        A row left `RUNNING` is the worst state in this table. `claim_queued` only selects
        `QUEUED` so nothing revisits it, and `has_pending_for_title` counts it as pending so
        the studio is refused every time they ask for another — permanently, with the screen
        showing a backfill that is forever in progress.
        """
        try:
            await self._session.rollback()
            backfill = await self._backfill_repository.get_by_id(backfill_id)
            if backfill is None:  # pragma: no cover — claimed moments ago
                return
            backfill.status = CollectionBackfillStatus.FAILED
            backfill.finished_at = datetime.now(UTC)
            backfill.failure_reason = ABANDONED_REASON
            backfill.is_depth_limited = True
            await self._session.commit()
        except Exception:
            _logger.exception("collection.backfill.abandon_failed", backfill_id=str(backfill_id))


def _charged_for(result: CollectionResult) -> float:
    """What one collected page cost, priced off the endpoint that served it.

    Read back from the catalogue by key rather than passed down, so the page and its price
    cannot disagree about which endpoint answered — the routing can change between one page
    of a walk and the next.
    """
    endpoint = get_endpoint(result.endpoint_key)
    if endpoint is None:  # pragma: no cover — the page came through this catalogue
        return 0.0
    return charged_cost_for_page(endpoint, result.fetched)

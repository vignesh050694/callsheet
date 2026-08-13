"""Executing one collection cycle: every variant, every platform, each post once (E03-S01).

A cycle is a fan-out. The title's identity set becomes several overlapping queries
(`query_plan`), each is run once per configured platform, and the pages that come back are
merged into a corpus in which a post appears exactly once however many queries returned it.

Deduplication is not a step at the end. It is a property of the write: `CollectionService`
skips ids the title already holds and the `mentions` unique constraint refuses the rest, so
the fan-out cannot inflate volume even if this service is wrong about what it has seen.
What *this* service owns is the other half of that trade — the record of which variants
matched, which deduplication would otherwise destroy.

Failure is per-platform, not per-cycle. A platform whose endpoint has no adapter, or whose
transport refuses, must not stop the platforms that work; and a cycle that fails outright
must still queue its successor, or one bad poll ends collection for a title permanently and
silently.
"""

import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.core.platforms import Platform
from app.models.collection_run import (
    FAILURE_REASON_MAX_LENGTH,
    CollectionRun,
    CollectionRunStatus,
)
from app.models.mention_query_match import MentionQueryMatch
from app.models.title import Title
from app.repositories.collection_run_repository import CollectionRunRepository
from app.repositories.mention_query_match_repository import MentionQueryMatchRepository
from app.repositories.mention_repository import MentionRepository
from app.repositories.title_repository import TitleRepository
from app.services.collection.query_plan import QueryVariant, build_query_variants
from app.services.collection.spend_policy import SpendPolicy
from app.services.collection_schedule_service import CollectionScheduleService
from app.services.collection_service import CollectionService
from app.services.title_service import TitleService

_logger = structlog.get_logger(__name__)

TITLE_GONE_REASON = "the title was deleted before its cycle ran"
NO_VARIANTS_REASON = "the title's identity set produced no query to run"
ABANDONED_REASON = "the cycle's own completion path failed; closed so the title can poll again"


@dataclass
class _CycleTotals:
    """What a cycle accumulated, across every variant and platform in it."""

    variants_planned: int = 0
    pages_fetched: int = 0
    mentions_stored: int = 0
    mentions_already_known: int = 0
    unreadable: int = 0
    variants_attributed: int = 0
    platforms_collected: set[Platform] = field(default_factory=set)
    platforms_skipped: dict[Platform, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CollectionCycleResult:
    """One finished cycle, in the terms collection health reports on (E03-S05)."""

    run_id: uuid.UUID
    title_id: uuid.UUID
    status: CollectionRunStatus
    variants_planned: int
    pages_fetched: int
    mentions_stored: int
    mentions_already_known: int
    unreadable: int
    platforms_collected: tuple[Platform, ...]
    platforms_skipped: tuple[Platform, ...]
    failure_reason: str | None
    next_run_at: datetime | None

    @property
    def did_collect(self) -> bool:
        return self.status is CollectionRunStatus.SUCCEEDED


class CollectionRunService:
    def __init__(
        self,
        session: AsyncSession,
        collection_service: CollectionService,
        schedule_service: CollectionScheduleService,
        spend_policy: SpendPolicy,
        settings: Settings,
    ) -> None:
        self._session = session
        self._run_repository = CollectionRunRepository(session)
        self._title_repository = TitleRepository(session)
        self._mention_repository = MentionRepository(session)
        self._match_repository = MentionQueryMatchRepository(session)
        self._collection_service = collection_service
        self._schedule_service = schedule_service
        self._spend_policy = spend_policy
        self._settings = settings

    async def run_due_cycles(
        self, *, now: datetime | None = None, limit: int | None = None
    ) -> list[CollectionCycleResult]:
        """Claims every cycle that has fallen due and runs them one after another."""
        claimed_at = now or datetime.now(UTC)
        batch_size = limit or self._settings.collection_worker_batch_size

        # Before claiming, not after. A title whose cadence has just escalated may have a
        # cycle that is not due at its old rate but is at its new one, and reconciling first
        # is what lets that cycle be claimed in this same tick rather than the next.
        await self._reconcile_cadence(claimed_at)

        runs = await self._run_repository.claim_due(claimed_at, limit=batch_size)
        # Committed before any polling starts. The claim has to be visible to other
        # workers immediately, and holding the transaction open across a minutes-long
        # cycle would keep the queue row locked for its whole duration.
        await self._session.commit()

        if not runs:
            _logger.debug("collection.worker.nothing_due")
            return []

        _logger.info("collection.worker.claimed", runs=len(runs))

        # Ids, not instances, are what carry across the batch. Every run in a tick shares
        # one session, and a rollback anywhere in it expires *every* instance attached to
        # that session — so a neighbour's handled failure silently poisons the ORM objects
        # of runs that have not started yet. Reading `run.id` off one of those raises
        # `MissingGreenlet` from synchronous attribute access, which is how one bad title
        # took a healthy one down with it even after the loop was made to catch exceptions.
        # Isolation has to re-establish state, not merely catch.
        run_ids = [run.id for run in runs]

        results: list[CollectionCycleResult] = []
        for run_id in run_ids:
            try:
                run = await self._run_repository.get_by_id(run_id)
                if run is None:  # pragma: no cover — claimed moments ago
                    _logger.warning("collection.worker.run_vanished", run_id=str(run_id))
                    continue
                results.append(await self.execute_run(run))
            except Exception:
                _logger.exception("collection.worker.run_abandoned", run_id=str(run_id))
                await self._abandon(run_id)
        return results

    async def _reconcile_cadence(self, now: datetime) -> None:
        """Brings queued cycles into line with their titles' current cadence (E03-S02).

        Isolated from the rest of the tick on purpose. Reconciliation is an optimisation —
        every cycle it touches would eventually run at the right rate anyway, one interval
        later — so a failure here must not stop cycles that are already due from being
        claimed. Logged at error rather than swallowed silently, because a title stuck at
        dormant rates through its release week is a real product failure even though nothing
        crashed.
        """
        try:
            advanced = await self._schedule_service.reconcile_pending_cadence(
                now=now, limit=self._settings.collection_cadence_reconcile_batch_size
            )
            if advanced:
                await self._session.commit()
        except Exception:
            _logger.exception("collection.worker.cadence_reconcile_failed")
            await self._session.rollback()

    async def _abandon(self, run_id: uuid.UUID) -> None:
        """Last resort: close a run whose own completion path failed.

        A run left `RUNNING` is the worst state in this table and the hardest to notice.
        `claim_due` only ever selects `QUEUED`, so nothing revisits it; meanwhile
        `has_pending_for_title` counts it as owed, so no successor is ever queued; and
        `is_stalled` reads `False`, so the dashboard reports the title as healthy while it
        has silently stopped collecting forever. Marking it failed makes all three tell the
        truth, and the next tick is free to queue a successor.

        Takes an id and reloads, rather than taking the instance the caller was holding:
        this runs immediately after a failure, where that instance is exactly the thing
        that cannot be trusted.
        """
        try:
            await self._session.rollback()
            run = await self._run_repository.get_by_id(run_id)
            if run is None:  # pragma: no cover — the row was claimed moments ago
                return
            run.status = CollectionRunStatus.FAILED
            run.finished_at = datetime.now(UTC)
            run.failure_reason = ABANDONED_REASON
            await self._session.commit()
        except Exception:
            # Nothing further can be done from this session. Logged at error because a run
            # genuinely stuck in `RUNNING` needs a human, not a retry.
            _logger.exception("collection.worker.abandon_failed", run_id=str(run_id))

    async def execute_run(self, run: CollectionRun) -> CollectionCycleResult:
        """Runs one claimed cycle to completion, and queues the next one either way."""
        started_at = time.perf_counter()
        title = await self._title_repository.get_by_id(run.title_id)
        if title is None:
            # No successor is queued: there is nothing left to collect for.
            return await self._finish(run, CollectionRunStatus.FAILED, TITLE_GONE_REASON, None)

        # Read once, up front, and used for every log line below. After a rollback these
        # attributes are expired, and reading an expired attribute is *synchronous* Python
        # that needs to issue a query — which is precisely what an async session cannot do,
        # so the log statement written to report the failure would raise `MissingGreenlet`
        # on top of it and take the worker down with the run still marked `running`.
        run_id, title_id = run.id, title.id

        totals = _CycleTotals()
        try:
            status, reason = await self._collect_for_title(run, title, totals)
        except Exception as error:
            # Broad on purpose. Anything that escapes a poll — a provider returning
            # nonsense, a dropped connection, a bug in an adapter — must still close this
            # run and queue the next one. An uncaught exception here would leave the row
            # `running` forever: the claim query skips it, `has_pending_for_title` sees it
            # as owed, and the title never polls again with nothing on any screen to say so.
            status, reason = CollectionRunStatus.FAILED, f"{type(error).__name__}: {error}"
            _logger.exception(
                "collection.cycle.failed",
                run_id=str(run_id),
                title_id=str(title_id),
                error_type=type(error).__name__,
            )
            await self._recover_session(run, title)

        result = await self._finish(run, status, reason, totals, title=title)

        _logger.info(
            "collection.cycle.completed",
            run_id=str(run_id),
            title_id=str(title_id),
            status=str(status),
            variants=totals.variants_planned,
            pages=totals.pages_fetched,
            stored=totals.mentions_stored,
            already_known=totals.mentions_already_known,
            unreadable=totals.unreadable,
            attributed=totals.variants_attributed,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
        )
        return result

    async def _queue_successor(self, title: Title, after: datetime) -> CollectionRun | None:
        """Queues the next cycle, and never lets that failure escape.

        The successor is queued whatever this cycle's outcome was — succeeded, skipped, or
        failed. A title that stops being polled because one poll went wrong is the failure
        this whole story exists to remove, and it is the one nobody would notice: the
        dashboard keeps showing the numbers it already had.

        An `IntegrityError` here is benign and expected under concurrency. It means another
        process queued this title's successor between the close above and this insert, and
        the partial unique index refused the duplicate — which is the index doing its job,
        not an error. The title has its next cycle either way.
        """
        # Read before anything can roll back. A rollback expires every instance, and
        # reading an expired attribute is synchronous Python that has to issue a query,
        # which an async session cannot do — so `str(title.id)` inside the handlers below
        # would raise `MissingGreenlet` on top of the failure it was written to report.
        title_id = title.id
        try:
            next_run = await self._schedule_service.queue_next_run(title, after=after)
            await self._session.commit()
            return next_run
        except IntegrityError:
            await self._session.rollback()
            _logger.info("collection.cycle.successor_already_queued", title_id=str(title_id))
            return None
        except Exception:
            # The run itself is already closed and committed, so the ledger is truthful
            # and the title reads as stalled. Error level: it will not recover on its own.
            await self._session.rollback()
            _logger.exception("collection.cycle.successor_not_queued", title_id=str(title_id))
            return None

    async def _recover_session(self, run: CollectionRun, title: Title) -> None:
        """Rolls back the failed work, then makes both rows usable again.

        The refreshes are the whole point and they are not optional. A rollback expires
        every instance in the session, and the next thing this service does is write the
        run's outcome and read the title's rate — ordinary attribute access, which for an
        expired instance means a query, issued from synchronous Python where an async
        session cannot run one. Reloading here, inside `await`, is what lets the failure
        path do its job instead of failing in a second, more confusing way.
        """
        await self._session.rollback()
        await self._session.refresh(run)
        await self._session.refresh(title)

    async def _collect_for_title(
        self, run: CollectionRun, title: Title, totals: _CycleTotals
    ) -> tuple[CollectionRunStatus, str | None]:
        """The body of a cycle: check it may run, plan it, then poll every platform."""
        decision = await self._spend_policy.decide(title.organization_id)
        if not decision.is_allowed:
            _logger.warning(
                "collection.cycle.refused_by_spend_policy",
                run_id=str(run.id),
                title_id=str(title.id),
                reason=decision.reason,
            )
            return CollectionRunStatus.SKIPPED, decision.reason

        variants = build_query_variants(title, limit=self._settings.collection_variants_per_title)
        totals.variants_planned = len(variants)
        if not variants:
            return CollectionRunStatus.SKIPPED, NO_VARIANTS_REASON

        for platform in self._settings.collection_platforms:
            await self._collect_platform(title, platform, variants, totals)

        return self._verdict(totals)

    async def _collect_platform(
        self,
        title: Title,
        platform: Platform,
        variants: list[QueryVariant],
        totals: _CycleTotals,
    ) -> None:
        """Every variant against one platform, abandoning the platform on a routing refusal.

        A `ServiceUnavailableError` here means the platform itself is unusable — no
        endpoint configured, no adapter for the one that is, no transport — so the
        remaining variants would raise the identical error four more times and charge
        nothing for the privilege. It is recorded once and the platform is dropped for this
        cycle only; the next cycle tries again, because the fix is a configuration change
        somebody may have made in the meantime.
        """
        for variant in variants:
            try:
                await self._collect_variant(title, platform, variant, totals)
            except ServiceUnavailableError as error:
                totals.platforms_skipped[platform] = error.message
                _logger.warning(
                    "collection.cycle.platform_unavailable",
                    title_id=str(title.id),
                    platform=str(platform),
                    variant=variant.key,
                    reason=error.message,
                )
                return
        totals.platforms_collected.add(platform)

    async def _collect_variant(
        self,
        title: Title,
        platform: Platform,
        variant: QueryVariant,
        totals: _CycleTotals,
    ) -> None:
        """One page for one query, stored and then credited to the variant that found it."""
        result = await self._collection_service.collect_page(
            title.id,
            platform,
            variant.query,
            limit=self._settings.collection_page_size,
            # The title's exclusion rules travel with the page (E02-S05). A post the
            # studio has already disowned is still stored — it was paid for, and the
            # judgement is reversible — but it is marked on arrival so it never reaches a
            # count. The alternative, sweeping after the fact, leaves a window where the
            # dashboard reports a number the studio was told would not happen again.
            excluded_terms=TitleService.excluded_terms_for(title),
        )
        totals.pages_fetched += 1
        totals.mentions_stored += result.stored
        totals.mentions_already_known += result.already_known
        totals.unreadable += result.unreadable

        totals.variants_attributed += await self._attribute(
            title.id, platform, variant, result.seen_external_ids
        )

    async def _attribute(
        self,
        title_id: uuid.UUID,
        platform: Platform,
        variant: QueryVariant,
        external_ids: tuple[str, ...],
    ) -> int:
        """Records that this variant returned these posts, without double-counting.

        Runs over every id the page returned, not only the ones this cycle stored. The
        scenario this story is written around is one post matching three variants inside a
        single cycle: the first stores it, the other two see it as already known, and all
        three found it. Crediting only new rows would attribute a popular post entirely to
        whichever query happened to run first.
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

        # A term approved from the suggestion list was credited against these posts before
        # it had ever run (E02-S04). It has now genuinely run and returned them, so the
        # credit is upgraded — the insert below cannot do it, because the row already
        # exists and `existing_pairs` correctly reports the pair as credited.
        await self._match_repository.promote_retroactive_to_collection(
            list(mention_ids.values()), variant.key
        )

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
        return len(matches)

    @staticmethod
    def _verdict(totals: _CycleTotals) -> tuple[CollectionRunStatus, str | None]:
        """Whether a cycle that ran to the end actually collected anything.

        A cycle in which every platform was unusable must not report success. Zero
        mentions from a working poll and zero mentions because nothing was polled look the
        same on a dashboard, and only one of them is news about the film.
        """
        if totals.platforms_collected:
            return CollectionRunStatus.SUCCEEDED, None
        if totals.platforms_skipped:
            return CollectionRunStatus.SKIPPED, "; ".join(
                f"{platform}: {reason}" for platform, reason in totals.platforms_skipped.items()
            )
        return CollectionRunStatus.SKIPPED, "no platform is configured for collection"

    async def _finish(
        self,
        run: CollectionRun,
        status: CollectionRunStatus,
        reason: str | None,
        totals: _CycleTotals | None,
        *,
        title: Title | None = None,
    ) -> CollectionCycleResult:
        """Closes the run row, then queues the successor — in that order, separately.

        Two transactions rather than one, and the order is forced rather than chosen.
        `uq_collection_run_one_pending_per_title` counts a `RUNNING` row as pending, so a
        successor inserted while this run is still open would collide with the run that is
        inserting it.

        Closing first is also the safer failure mode. Queuing the successor can fail — a
        cadence misconfiguration, a lost connection, another process having queued it
        already — and if that happened inside the same transaction as the close, the close
        would roll back with it and leave the run `RUNNING`: invisible, unclaimable, and
        reported as healthy. Closed-with-no-successor is the honest version of the same
        accident. The title shows as stalled, which is exactly what it is.
        """
        finished_at = datetime.now(UTC)
        run.status = status
        run.finished_at = finished_at
        run.failure_reason = reason[:FAILURE_REASON_MAX_LENGTH] if reason else None
        if totals is not None:
            run.variants_planned = totals.variants_planned
            run.pages_fetched = totals.pages_fetched
            run.mentions_stored = totals.mentions_stored
            run.mentions_already_known = totals.mentions_already_known
            run.unreadable = totals.unreadable
        await self._session.commit()

        # Snapshotted here, while the instance is certainly loaded, and never read again
        # afterwards. Queuing the successor below can roll back, and a rollback expires
        # every attribute on `run` — so building this result from the instance after that
        # call turned a handled failure into an unhandled `MissingGreenlet` and put the
        # stuck-`RUNNING` row back, one layer further out than where it was first fixed.
        closed = CollectionCycleResult(
            run_id=run.id,
            title_id=run.title_id,
            status=status,
            variants_planned=run.variants_planned,
            pages_fetched=run.pages_fetched,
            mentions_stored=run.mentions_stored,
            mentions_already_known=run.mentions_already_known,
            unreadable=run.unreadable,
            platforms_collected=tuple(sorted(totals.platforms_collected)) if totals else (),
            platforms_skipped=tuple(sorted(totals.platforms_skipped)) if totals else (),
            failure_reason=run.failure_reason,
            next_run_at=None,
        )

        if title is None:
            return closed
        next_run = await self._queue_successor(title, finished_at)
        return replace(closed, next_run_at=next_run.scheduled_for if next_run is not None else None)

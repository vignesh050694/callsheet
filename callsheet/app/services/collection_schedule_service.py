"""Deciding that a title is owed a collection cycle, and when (E03-S01).

The promise this story makes is that collection starts *without anyone provisioning a job*.
That promise is kept here, in two places and nowhere else: a run is queued inside the
transaction that creates a title, and the next one is queued as each cycle finishes.

Queuing inside the create transaction is deliberate. Enqueuing afterwards — a callback, a
post-commit hook, a message published on the way out — leaves a window in which a title
exists with nothing owed to it, and a title in that state is not visibly broken. It has a
dashboard, an identity set, and no mentions, which is indistinguishable from a film nobody
is talking about. The cost of the stricter coupling is that a failure to queue fails the
title creation, which is the error anyone would rather have.

*How often* is not decided here. That is the `CadencePolicy` — since E03-S02, a phase-driven
one. What this service adds on top of it is **reconciliation**: a cadence decision made when
a cycle was queued can be twelve hours stale by the time that cycle runs, and a dormant title
that becomes newsworthy cannot wait out its own interval to find out it should be polling
harder. `reconcile_pending_cadence` re-asks the policy about cycles that are already queued.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_run import CollectionRun, CollectionRunStatus, CollectionRunTrigger
from app.models.title import Title
from app.repositories.collection_run_repository import CollectionRunRepository
from app.repositories.title_repository import TitleRepository
from app.services.collection.cadence import CadenceDecision, CadencePolicy, interval_for_rate

_logger = structlog.get_logger(__name__)


class CollectionScheduleService:
    def __init__(self, session: AsyncSession, cadence: CadencePolicy) -> None:
        self._session = session
        self._run_repository = CollectionRunRepository(session)
        self._title_repository = TitleRepository(session)
        self._cadence = cadence

    async def queue_first_run(self, title: Title, *, now: datetime | None = None) -> CollectionRun:
        """The cycle a title is owed the moment it exists.

        Due immediately rather than one interval out. The story asks for a first run queued
        within a minute of setup and real mentions inside a day, and the first cycle is also
        the one that seeds alias discovery (E02-S04) — waiting two hours to start would
        spend the whole of the product's first impression on an empty dashboard.

        Does not commit. The caller owns the transaction, and that is the entire point:
        the title and its first cycle land together or not at all.
        """
        queued_at = now or datetime.now(UTC)
        run = self._build_run(
            title,
            trigger=CollectionRunTrigger.TITLE_CREATED,
            scheduled_for=queued_at,
            decision=await self._cadence.decide(title, now=queued_at),
        )
        self._run_repository.add(run)
        _logger.info(
            "collection.schedule.first_run_queued",
            title_id=str(title.id),
            scheduled_for=queued_at.isoformat(),
            polls_per_day=run.polls_per_day,
            cadence_phase=str(run.cadence_phase),
        )
        return run

    async def queue_next_run(
        self, title: Title, *, after: datetime, trigger: CollectionRunTrigger | None = None
    ) -> CollectionRun | None:
        """The cycle following one that has just finished, if none is already owed.

        Returns `None` when the title already has a queued or running cycle. What stops a
        title's rate drifting upward is not this check, though — it is
        `uq_collection_run_one_pending_per_title`. A read followed by an insert is a race:
        two processes both see nothing pending and both queue one, which is reachable in
        shipped code the moment an operator's `--title-id` lands beside a worker finishing
        a cycle. The result is a title polled twice per cycle at twice the cost, with two
        workers then claiming both rows and colliding on the `mentions` unique constraint.

        The check stays because it is cheap and it turns the ordinary case into a clean
        `None` rather than an exception. The constraint is what makes it true.
        """
        if await self._run_repository.has_pending_for_title(title.id):
            _logger.debug("collection.schedule.already_pending", title_id=str(title.id))
            return None

        # Decided once and used for both the schedule and the stamp. Asking twice would let
        # a title be scheduled at one rate and recorded at another, which is the kind of
        # disagreement nobody finds until they are reconciling an invoice against a chart.
        decision = await self._cadence.decide(title, now=after)
        scheduled_for = decision.next_run_at(after=after)
        run = self._build_run(
            title,
            trigger=trigger or CollectionRunTrigger.SCHEDULED,
            scheduled_for=scheduled_for,
            decision=decision,
        )
        self._run_repository.add(run)
        _logger.info(
            "collection.schedule.next_run_queued",
            title_id=str(title.id),
            scheduled_for=scheduled_for.isoformat(),
            polls_per_day=run.polls_per_day,
            cadence_phase=str(run.cadence_phase),
            is_volume_escalated=run.is_volume_escalated,
        )
        return run

    async def queue_manual_run(
        self, title: Title, *, now: datetime | None = None
    ) -> CollectionRun | None:
        """An out-of-band cycle, due immediately.

        Subject to the same "one pending cycle per title" rule as any other enqueue, so
        asking for a poll while one is already owed returns `None` rather than adding a
        second. An operator who wants it sooner is better served by the cycle that already
        exists than by a duplicate of it.
        """
        if await self._run_repository.has_pending_for_title(title.id):
            _logger.info("collection.schedule.manual_run_declined", title_id=str(title.id))
            return None

        queued_at = now or datetime.now(UTC)
        run = self._build_run(
            title,
            trigger=CollectionRunTrigger.MANUAL,
            scheduled_for=queued_at,
            decision=await self._cadence.decide(title, now=queued_at),
        )
        self._run_repository.add(run)
        _logger.info("collection.schedule.manual_run_queued", title_id=str(title.id))
        return run

    async def pending_run_for_title(self, title_id: uuid.UUID) -> CollectionRun | None:
        return await self._run_repository.next_pending_for_title(title_id)

    async def reconcile_pending_cadence(
        self, *, now: datetime | None = None, limit: int
    ) -> int:
        """Re-asks the cadence policy about cycles that are already queued (E03-S02).

        Without this, a cadence decision only ever changes when a cycle *finishes*, so the
        speed at which a title can react to its own escalation is capped by the rate it is
        escalating away from. A dormant title on 2/day takes up to twelve hours to notice
        that it should be on 12/day, which is most of a news cycle. Run from the worker tick,
        the reaction is bounded by the tick instead.

        **One-directional: this can only ever make a title poll sooner.** A de-escalation is
        left to take effect when the current cycle queues its successor, costing at most one
        poll at the old rate. Rescheduling in both directions would let a policy that
        oscillates keep pushing a due cycle away from itself, and a title that never polls is
        a far worse outcome than a title that polls once more than it needed to.

        Does not commit. The caller owns the transaction, as everywhere else in this service.
        """
        moment = now or datetime.now(UTC)
        if limit <= 0:
            return 0

        runs = await self._run_repository.list_queued_scheduled_furthest_first(
            moment, limit=limit
        )
        advanced = 0
        for run in runs:
            if await self._advance_if_escalated(run, now=moment):
                advanced += 1

        if advanced:
            _logger.info(
                "collection.schedule.cadence_reconciled",
                examined=len(runs),
                advanced=advanced,
            )
        return advanced

    async def _advance_if_escalated(self, run: CollectionRun, *, now: datetime) -> bool:
        """Pulls one queued cycle forward if its title's cadence has risen since it was set.

        The anchor — the instant the current schedule was measured from — is recovered as
        `scheduled_for` minus the interval implied by the rate stamped on the run, because
        that is exactly the arithmetic that produced `scheduled_for`. Recomputing from the
        anchor rather than from `now` is what makes this idempotent: reconciling the same run
        on ten consecutive ticks gives the same answer as reconciling it once, whereas
        `now + interval` would push the cycle a tick further out every time it ran.
        """
        title = await self._title_repository.get_by_id(run.title_id)
        if title is None:  # pragma: no cover — a deleted title cascades its runs away
            return False

        decision = await self._cadence.decide(title, now=now)
        if decision.polls_per_day <= run.polls_per_day:
            return False

        anchor = run.scheduled_for - interval_for_rate(run.polls_per_day)
        rescheduled_for = decision.next_run_at(after=anchor)
        if rescheduled_for >= run.scheduled_for:  # pragma: no cover — a faster rate is sooner
            return False

        _logger.info(
            "collection.schedule.cadence_advanced",
            title_id=str(title.id),
            run_id=str(run.id),
            from_polls_per_day=run.polls_per_day,
            to_polls_per_day=decision.polls_per_day,
            cadence_phase=str(decision.phase),
            is_volume_escalated=decision.is_volume_escalated,
            was_scheduled_for=run.scheduled_for.isoformat(),
            now_scheduled_for=rescheduled_for.isoformat(),
        )
        run.scheduled_for = rescheduled_for
        run.polls_per_day = decision.polls_per_day
        run.cadence_phase = decision.phase
        run.is_volume_escalated = decision.is_volume_escalated
        return True

    def _build_run(
        self,
        title: Title,
        *,
        trigger: CollectionRunTrigger,
        scheduled_for: datetime,
        decision: CadenceDecision,
    ) -> CollectionRun:
        return CollectionRun(
            title_id=title.id,
            status=CollectionRunStatus.QUEUED,
            trigger=trigger,
            scheduled_for=scheduled_for,
            # Stamped from the policy at queue time rather than read back from settings
            # when the run executes, so a rate changed mid-campaign leaves a history of
            # what each cycle was actually scheduled at.
            polls_per_day=decision.polls_per_day,
            cadence_phase=decision.phase,
            is_volume_escalated=decision.is_volume_escalated,
        )

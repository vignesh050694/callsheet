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

*How often* is not decided here. That is the `CadencePolicy`, which E03-S02 replaces.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_run import CollectionRun, CollectionRunStatus, CollectionRunTrigger
from app.models.title import Title
from app.repositories.collection_run_repository import CollectionRunRepository
from app.services.collection.cadence import CadencePolicy

_logger = structlog.get_logger(__name__)


class CollectionScheduleService:
    def __init__(self, session: AsyncSession, cadence: CadencePolicy) -> None:
        self._session = session
        self._run_repository = CollectionRunRepository(session)
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
        )
        self._run_repository.add(run)
        _logger.info(
            "collection.schedule.first_run_queued",
            title_id=str(title.id),
            scheduled_for=queued_at.isoformat(),
            polls_per_day=run.polls_per_day,
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

        scheduled_for = self._cadence.next_run_at(title, after=after)
        run = self._build_run(
            title,
            trigger=trigger or CollectionRunTrigger.SCHEDULED,
            scheduled_for=scheduled_for,
        )
        self._run_repository.add(run)
        _logger.info(
            "collection.schedule.next_run_queued",
            title_id=str(title.id),
            scheduled_for=scheduled_for.isoformat(),
            polls_per_day=run.polls_per_day,
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
        )
        self._run_repository.add(run)
        _logger.info("collection.schedule.manual_run_queued", title_id=str(title.id))
        return run

    async def pending_run_for_title(self, title_id: uuid.UUID) -> CollectionRun | None:
        return await self._run_repository.next_pending_for_title(title_id)

    def _build_run(
        self,
        title: Title,
        *,
        trigger: CollectionRunTrigger,
        scheduled_for: datetime,
    ) -> CollectionRun:
        return CollectionRun(
            title_id=title.id,
            status=CollectionRunStatus.QUEUED,
            trigger=trigger,
            scheduled_for=scheduled_for,
            # Stamped from the policy at queue time rather than read back from settings
            # when the run executes, so a rate changed mid-campaign leaves a history of
            # what each cycle was actually scheduled at.
            polls_per_day=self._cadence.polls_per_day(title),
        )

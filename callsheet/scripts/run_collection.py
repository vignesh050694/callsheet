"""The collection worker: claims due cycles and runs them (E03-S01).

    uv run python -m scripts.run_collection --once
    uv run python -m scripts.run_collection                    # loops on the configured tick
    uv run python -m scripts.run_collection --title-id <uuid>  # force one cycle now

A separate process rather than a background task inside the API. Two reasons, and the
second is the one that matters: a poll is minutes of network work, so running it in the web
process ties collection throughput to request capacity; and the API is deployed in more
than one replica, which would mean every replica polling every title. Here the queue
decides who does the work, and running two workers is a deliberate act that `SKIP LOCKED`
already makes safe.

`--title-id` exists because otherwise nothing in this story can be *observed* except by
waiting for a schedule. It queues an ordinary cycle — same rate, same policy — and declines
if the title already has one owed, so it cannot be used to poll a title faster than its
cadence allows.
"""

import argparse
import asyncio
import contextlib
import signal
import sys
import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import DomainError
from app.core.logging_config import configure_logging
from app.db.session import engine, session_factory
from app.repositories.title_repository import TitleRepository
from app.services.collection.cadence import FixedCadencePolicy
from app.services.collection.monid_source import MonidCollectionSource
from app.services.collection.spend_policy import UnrestrictedSpendPolicy
from app.services.collection_run_service import CollectionCycleResult, CollectionRunService
from app.services.collection_schedule_service import CollectionScheduleService
from app.services.collection_service import CollectionService

_logger = structlog.get_logger(__name__)

TITLE_NOT_FOUND_MESSAGE = "Title {id} was not found"


def _build_run_service(session: AsyncSession, settings: Settings) -> CollectionRunService:
    """The same wiring `deps.py` gives the API, assembled without a request to hang it off.

    Resolved here rather than injected because this process has no FastAPI request. It is
    deliberately the identical set of bindings — a worker that polled through a different
    transport or a different spend policy than the application would be untestable by any
    means the application offers.
    """
    from app.api.deps import get_monid_transport

    source = MonidCollectionSource(get_monid_transport(), settings)
    return CollectionRunService(
        session,
        CollectionService(session, source),
        CollectionScheduleService(session, FixedCadencePolicy(settings.collection_polls_per_day)),
        UnrestrictedSpendPolicy(),
        settings,
    )


async def _queue_manual_cycle(title_id: uuid.UUID, settings: Settings) -> bool:
    """Queues one out-of-band cycle. Returns whether anything was added.

    The `IntegrityError` path is the race this command is most likely to lose: an operator
    types this while a worker is finishing a cycle for the same title, both see nothing
    pending, and `uq_collection_run_one_pending_per_title` refuses the second insert. That
    is the constraint working, and the operator's intent — "make sure this title has a
    cycle owed to it" — is satisfied by the one that won.
    """
    async with session_factory() as session:
        title = await TitleRepository(session).get_by_id(title_id)
        if title is None:
            raise DomainError(TITLE_NOT_FOUND_MESSAGE.format(id=title_id))

        schedule_service = CollectionScheduleService(
            session, FixedCadencePolicy(settings.collection_polls_per_day)
        )
        run = await schedule_service.queue_manual_run(title)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            _logger.info("collection.worker.manual_run_lost_race", title_id=str(title_id))
            return False
        return run is not None


async def _run_one_tick(settings: Settings) -> list[CollectionCycleResult]:
    async with session_factory() as session:
        service = _build_run_service(session, settings)
        return await service.run_due_cycles()


async def _run_forever(settings: Settings, stopping: asyncio.Event) -> None:
    """Ticks until asked to stop, sleeping between ticks rather than spinning.

    A tick that raises is logged and the loop continues. The daemon is the only thing
    keeping every title collecting, so a single bad tick — a database blip, one malformed
    title — must not end polling for the entire deployment. Each tick opens its own
    session, so the next one starts clean regardless of how the last one ended.
    """
    interval = settings.collection_worker_interval_seconds
    _logger.info("collection.worker.started", interval_seconds=interval)
    while not stopping.is_set():
        try:
            for result in await _run_one_tick(settings):
                _report(result)
        except Exception:
            _logger.exception("collection.worker.tick_failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stopping.wait(), timeout=interval)
    _logger.info("collection.worker.stopped")


def _report(result: CollectionCycleResult) -> None:
    print(
        f"run={result.run_id} title={result.title_id} status={result.status} "
        f"variants={result.variants_planned} pages={result.pages_fetched} "
        f"stored={result.mentions_stored} known={result.mentions_already_known} "
        f"unreadable={result.unreadable} "
        f"collected={','.join(str(p) for p in result.platforms_collected) or '-'} "
        f"skipped={','.join(str(p) for p in result.platforms_skipped) or '-'} "
        f"next={result.next_run_at.isoformat() if result.next_run_at else '-'}"
        + (f" reason={result.failure_reason}" if result.failure_reason else "")
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run due collection cycles.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Claim and run whatever is due right now, then exit.",
    )
    parser.add_argument(
        "--title-id",
        type=uuid.UUID,
        help="Queue one cycle for this title before ticking, if none is already owed.",
    )
    return parser


async def _main(arguments: argparse.Namespace, settings: Settings) -> int:
    if arguments.title_id is not None:
        if await _queue_manual_cycle(arguments.title_id, settings):
            print(f"Queued a cycle for title {arguments.title_id}.")
        else:
            print(f"Title {arguments.title_id} already has a cycle owed to it; queued nothing.")

    if arguments.once or arguments.title_id is not None:
        for result in await _run_one_tick(settings):
            _report(result)
        return 0

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for received in (signal.SIGINT, signal.SIGTERM):
        # A cycle in flight finishes and closes its run row; only the *next* tick is
        # skipped. Killing a worker mid-poll would leave the run `running` and the title
        # unpollable until somebody noticed.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(received, stopping.set)
    await _run_forever(settings, stopping)
    return 0


def main() -> int:
    arguments = _build_parser().parse_args()
    settings = get_settings()
    configure_logging(settings)

    async def _run() -> int:
        try:
            return await _main(arguments, settings)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except DomainError as error:
        print(f"Collection did not run: {error.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

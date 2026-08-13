"""Per-platform collection health for one title (E03-S05).

The read behind the dashboard header. It answers, for each platform a title collects from,
three questions a flat line cannot: when did this last work, is that recent enough for the
rate this title is currently polled at, and — if not — what is the last thing that went
wrong.

The freshness claim is assembled here rather than by each screen, because "as of" is the
sentence most likely to be quietly wrong. Two consumers computing it from the same raw
counts is two chances to disagree about whether a stale platform counts, and the whole point
of the story is that it must not.

`interval` comes from the title's **current** cadence phase, asked of the policy live for the
same reason `CollectionStatusService` asks live (E03-S02): a title that crossed into release
surge an hour ago is polled every half hour now, and judging its silence against the twelve
hours its dormant phase allowed would call an ongoing outage healthy for most of an opening
weekend.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.collection_health import (
    PlatformHealth,
    PlatformHealthState,
    freshness_as_of,
    health_state_for,
)
from app.core.config import Settings
from app.core.platforms import Platform
from app.core.timestamps import as_utc
from app.models.collection_platform_result import CollectionPlatformResult
from app.models.title import Title
from app.repositories.collection_platform_result_repository import (
    CollectionPlatformResultRepository,
)
from app.services.collection.cadence import CadenceDecision, CadencePolicy, interval_for_rate

_logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TitleCollectionHealth:
    """Every configured platform's health, and the freshness claim they permit."""

    title_id: uuid.UUID
    platforms: tuple[PlatformHealth, ...]
    # The oldest success among *reporting* platforms. `None` when nothing is reporting,
    # which must render as "no current data" rather than as an invented timestamp.
    data_as_of: datetime | None

    @property
    def stale_platforms(self) -> tuple[PlatformHealth, ...]:
        return tuple(health for health in self.platforms if health.is_stale)

    @property
    def has_stale_platform(self) -> bool:
        return bool(self.stale_platforms)

    @property
    def reporting_platforms(self) -> tuple[PlatformHealth, ...]:
        return tuple(health for health in self.platforms if health.state.is_reporting)


class CollectionHealthService:
    def __init__(
        self, session: AsyncSession, cadence: CadencePolicy, settings: Settings
    ) -> None:
        self._session = session
        self._result_repository = CollectionPlatformResultRepository(session)
        self._cadence = cadence
        self._settings = settings

    async def health_for_title(
        self,
        title: Title,
        *,
        now: datetime | None = None,
        cadence: CadenceDecision | None = None,
    ) -> TitleCollectionHealth:
        """Health for every platform this deployment collects from, reported or not.

        Iterates the *configured* platform list rather than the platforms that happen to
        have rows. A platform that has never once been attempted is exactly the one worth
        showing — it is what a misconfiguration looks like — and driving the list off the
        results table would make it invisible by being absent.

        `cadence` is accepted rather than always asked for, because the caller that matters
        most has already asked. `CollectionStatusService` needs the same decision to report
        the polling rate, and `PhaseCadencePolicy.decide` is not free — on a dormant title it
        issues a volume query to check for escalation. Deciding twice per title, on a screen
        that renders one status per row, doubled that query across the whole list. Passing it
        also guarantees the rate a studio is shown and the interval their staleness is judged
        against are the same decision rather than two taken moments apart.
        """
        moment = now or datetime.now(UTC)
        decision = cadence or await self._cadence.decide(title, now=moment)
        interval = interval_for_rate(decision.polls_per_day)

        last_success = await self._result_repository.last_success_at_by_platform(title.id)
        attempted = await self._result_repository.attempted_platforms(title.id)

        platforms = tuple(
            [
                await self._health_for_platform(
                    title.id,
                    platform,
                    last_successful_at=last_success.get(platform),
                    has_been_attempted=platform in attempted,
                    interval=interval,
                    now=moment,
                )
                for platform in self._settings.collection_platforms
            ]
        )

        health = TitleCollectionHealth(
            title_id=title.id,
            platforms=platforms,
            data_as_of=freshness_as_of(list(platforms)),
        )
        if health.has_stale_platform:
            _logger.info(
                "collection.health.stale_platforms",
                title_id=str(title.id),
                platforms=[str(stale.platform) for stale in health.stale_platforms],
                polls_per_day=decision.polls_per_day,
            )
        return health

    async def _health_for_platform(
        self,
        title_id: uuid.UUID,
        platform: Platform,
        *,
        last_successful_at: datetime | None,
        has_been_attempted: bool,
        interval: timedelta,
        now: datetime,
    ) -> PlatformHealth:
        # `as_utc` because `finished_at` comes back off a stored row — naive from SQLite,
        # aware from Postgres — and is about to be compared with a freshly computed instant.
        reconciled = as_utc(last_successful_at) if last_successful_at is not None else None
        state = health_state_for(
            last_successful_at=reconciled,
            has_been_attempted=has_been_attempted,
            interval=interval,
            tolerance=self._settings.collection_staleness_interval_tolerance,
            now=now,
        )

        # Only asked for when it changes what is shown. A reporting platform's last failure
        # is history, and putting it on the screen beside a healthy state is how a studio
        # ends up worrying about a poll that already recovered.
        #
        # This is one query per *non-reporting* platform rather than one batched read, which
        # is a deliberate trade rather than an oversight. It is bounded by the platform count
        # — four, and one today — and costs nothing at all on the healthy path, which is the
        # path a dashboard is almost always on. Batching it would mean a top-N-per-group
        # query, which neither Postgres nor SQLite express portably without a window
        # function; the version that fetches a flat slice and groups in Python can silently
        # drop a quiet platform's rows when a noisy one dominates the slice, and a coverage
        # screen that under-reports a gap is the one bug this story cannot ship.
        consecutive_failures = 0
        last_failure_reason = None
        if state is not PlatformHealthState.REPORTING:
            recent = await self._result_repository.recent_for_platform(
                title_id,
                platform,
                limit=self._settings.collection_platform_failure_window,
            )
            leading_failures = _leading_failures(recent)
            consecutive_failures = len(leading_failures)
            last_failure_reason = next(
                (
                    attempt.failure_reason
                    for attempt in leading_failures
                    if attempt.failure_reason
                ),
                None,
            )

        return PlatformHealth(
            platform=str(platform),
            state=state,
            last_successful_at=reconciled,
            last_failure_reason=last_failure_reason,
            consecutive_failures=consecutive_failures,
        )


def _leading_failures(
    recent: list[CollectionPlatformResult],
) -> list[CollectionPlatformResult]:
    """The unbroken run of failures at the newest end, stopping at the first success.

    Only the leading run counts, and the reason shown comes from it too. A platform that
    failed last week, recovered, and has just failed once is one failure deep — reading the
    reason off the whole window instead would report last week's outage as the current
    problem, which sends somebody to fix the wrong thing.
    """
    failures = []
    for attempt in recent:
        if attempt.status.is_reporting:
            break
        failures.append(attempt)
    return failures

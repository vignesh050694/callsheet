"""Tests for E03-S05 — Tell me when a platform stops reporting, instead of showing a flat
line as if it's calm.

Story: stories/E03-agentic-collection-layer/E03-S05-collection-health-and-coverage.md
Epic: stories/E03-agentic-collection-layer/EPIC.md

The story has exactly one Gherkin scenario, "One platform's endpoint fails during release
weekend", with six clauses (four Given, one When, one Then). Each is mapped to exactly one
test, named so the mapping is obvious:

  - Given 1, "my title collects from X, Reddit, YouTube, and Instagram" ->
    `test_given_a_title_collecting_from_all_four_platforms_has_one_health_entry_each`.
    Every configured platform gets an entry, in the configured order, whether or not it has
    ever been polled — the thing a screen keying off `settings.collection_platforms` needs
    to be true before anything else in this file matters.

  - Given 2, "the dashboard header shows a per-platform last-successful-collection time" ->
    `test_given_the_dashboard_shows_each_platforms_last_successful_collection_time`. Two
    platforms with distinct success times, and one of them with a *later* failed attempt on
    top — proving the header reads the last **success**, not the last attempt.

  - Given 3, "a platform is considered stale when it has missed the expected interval for
    its current cadence phase" ->
    `test_given_a_platform_is_stale_relative_to_its_current_cadence_phase`.
    The single most likely thing to be wrong per the task brief: the same last-success time
    and the same silence, judged against two different cadence phases, must disagree.

  - Given 4, "stale platforms are excluded from 'as of' freshness claims" ->
    `test_given_stale_platforms_are_excluded_from_the_as_of_freshness_claim`. A stale
    platform's *much older* success is what a buggy "oldest success over everyone" would
    return; the claim must come from the reporting platform instead.

  - When, "Instagram collection fails repeatedly through the surge window" ->
    `test_when_instagram_fails_repeatedly_every_cycle_records_it_unavailable`.
    Three real cycles through `CollectionRunService`, Instagram refusing every time while
    the other three platforms keep working — proving the failure is per-platform, not
    per-cycle, and that it is recorded every single time, not just once.

  - Then, "the dashboard shows Instagram as stale with its last successful time, and every
    chart containing Instagram data carries a visible warning that the platform is not
    currently reporting" ->
    `test_then_instagram_shows_stale_with_its_last_success_others_keep_reporting`.
    The backend half of "a visible warning on every chart" is `PlatformHealthState.STALE`
    surviving to `health_for_title`'s output next to three platforms still `REPORTING` — the
    structured fact a chart renders its warning from. The chart itself is UI and untested
    here (see the note on the frontend below).

That is six clauses, not the "~6, counting the Notes' alerting claim" the task brief
estimates — the scenario has four Given clauses, not three, so the notes claim is a seventh,
mapped on its own:

  - Notes, "Repeated failures should raise an internal alert to data ops before the customer
    notices" -> `test_notes_repeated_platform_failures_raise_an_internal_alert_to_data_ops`.

Five more, chosen against risk rather than coverage, from the task brief's own candidate
list:

  - `test_freshness_as_of_is_the_oldest_reporting_success_not_the_newest_and_null_with_`
    `nothing_reporting` — pins the *direction* explicitly (oldest, not newest) with times
    far enough apart that a max()-instead-of-min() bug cannot pass by accident, plus the
    empty case.

  - `test_a_brand_new_title_has_no_stale_platforms_but_an_attempted_never_succeeded_`
    `platform_is_stale` — the pending/stale split: a title with nothing attempted yet must
    not show a single stale platform, and a platform that has been tried and has never once
    succeeded must show stale immediately, however recently it was tried.

  - `test_a_platforms_finished_at_read_back_naive_from_sqlite_still_compares_correctly_`
    `against_aware_now` — this defect class has already bitten this epic twice (E03-S04,
    E03-S03). Pins the premise (SQLite hands `finished_at` back with no tzinfo) and the fix
    (it still compares correctly against a fresh aware `now`) in one test.

  - `test_consecutive_failures_counts_only_the_leading_run_and_its_reason_not_an_older_`
    `outage` — a platform that failed, recovered, then failed once more must read as one
    failure deep with *today's* reason, not three deep with last week's.

  - `test_an_alert_fires_exactly_at_the_threshold_not_below_it_and_a_raising_alerter_`
    `cannot_fail_the_cycle` — the boundary (two failures silent, the third fires exactly
    once) and the safety property (a paging integration that is itself down must not turn a
    working poll into a failed one) in one test.

No test calls Monid. `_PerPlatformSource` below plays the same role `SequencedTikhubTransport`
and `_FixedPageSource` play in the E03-S01/E03-S02 suites: a `CollectionSource` double, never
a transport double, so nothing here depends on a vendor payload shape.

**Frontend**: `callsheet-ui` has no test runner configured (confirmed by inspection — no
Vitest/Jest config, no test script beyond `npm run check`'s lint+typecheck+build). None is
introduced here, per the task brief. Every test in this file is a backend test; the story's
UI claims ("visible warning on every chart") are covered only to the extent that the
`PlatformHealthState` the frontend would key off arrives correctly in the backend's output.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cadence_phase import CadencePhase
from app.core.collection_endpoints import get_endpoint
from app.core.collection_health import (
    PlatformHealth,
    PlatformHealthState,
    freshness_as_of,
    health_state_for,
)
from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.core.platforms import Platform
from app.models.collection_platform_result import (
    CollectionPlatformResult,
    PlatformCollectionStatus,
)
from app.models.collection_run import CollectionRunStatus
from app.models.organization import Organization, OrganizationType
from app.models.title import Title
from app.repositories.collection_platform_result_repository import (
    CollectionPlatformResultRepository,
)
from app.repositories.collection_run_repository import CollectionRunRepository
from app.services.collection.cadence import CadenceDecision, CadencePolicy, FixedCadencePolicy
from app.services.collection.health_alerter import CollectionHealthAlerter
from app.services.collection.mention_shape import NormalizedMention
from app.services.collection.source import (
    CollectedItem,
    CollectionPage,
    CollectionSource,
    CollectionWindow,
)
from app.services.collection.spend_policy import UnrestrictedSpendPolicy
from app.services.collection_health_service import CollectionHealthService
from app.services.collection_run_service import CollectionRunService
from app.services.collection_schedule_service import CollectionScheduleService
from app.services.collection_service import CollectionService

# ---------------------------------------------------------------------------
# Section 0 — Fixtures and helpers.
# ---------------------------------------------------------------------------

ALL_FOUR_PLATFORMS = [Platform.X, Platform.REDDIT, Platform.YOUTUBE, Platform.INSTAGRAM]

_ENDPOINT_KEY_BY_PLATFORM = {
    Platform.X: "x.tikhub_search_timeline",
    Platform.INSTAGRAM: "instagram.tikhub_hashtag_search",
    Platform.REDDIT: "reddit.tikhub_dynamic_search",
    Platform.YOUTUBE: "youtube.tikhub_video_comments",
}


def _settings(**overrides: Any) -> Settings:
    """Every configured platform by default — the story's own "X, Reddit, YouTube, and
    Instagram" — with any story-specific knob overridable per test."""
    defaults: dict[str, Any] = {"collection_platforms": list(ALL_FOUR_PLATFORMS)}
    defaults.update(overrides)
    return Settings(**defaults)


async def _build_title(
    session: AsyncSession, *, release_date: date = date(2026, 8, 15), slug: str, name: str = "Nova"
) -> Title:
    """A title with no identity terms beyond its name — this story does not care what a
    cycle searches for, only what happened to each platform it tried."""
    organization = Organization(
        name="Sun Pictures", slug=slug, organization_type=OrganizationType.PRODUCTION_HOUSE
    )
    session.add(organization)
    await session.flush()
    title = Title(organization_id=organization.id, name=name, release_date=release_date)
    title.terms = []
    session.add(title)
    await session.flush()
    return title


async def _title_with_first_run(
    session: AsyncSession, cadence: CadencePolicy, *, slug: str
) -> Title:
    """A title with exactly one cycle owed to it, the way title creation leaves one
    (E03-S01) — what every test that runs a real cycle through `CollectionRunService`
    starts from."""
    title = await _build_title(session, slug=slug)
    await CollectionScheduleService(session, cadence).queue_first_run(title)
    await session.flush()
    return title


async def _any_run_id(session: AsyncSession, title: Title, cadence: CadencePolicy) -> uuid.UUID:
    """A real, persisted `CollectionRun` row to satisfy `CollectionPlatformResult`'s foreign
    key, for tests that write platform-result rows directly rather than through a live
    cycle — the tests below that need exact, hand-picked timestamps."""
    run = await CollectionScheduleService(session, cadence).queue_first_run(title)
    await session.flush()
    return run.id


def _platform_result(
    *,
    run_id: uuid.UUID,
    title_id: uuid.UUID,
    platform: Platform,
    status: PlatformCollectionStatus,
    finished_at: datetime,
    failure_reason: str | None = None,
) -> CollectionPlatformResult:
    return CollectionPlatformResult(
        collection_run_id=run_id,
        title_id=title_id,
        platform=platform,
        status=status,
        pages_fetched=1 if status is PlatformCollectionStatus.SUCCEEDED else 0,
        mentions_stored=1 if status is PlatformCollectionStatus.SUCCEEDED else 0,
        failure_reason=failure_reason,
        finished_at=finished_at,
    )


class _PerPlatformSource(CollectionSource):
    """Succeeds for every platform in `working`; refuses every platform in `failing` with
    `ServiceUnavailableError` on every call — the exact shape "Instagram's endpoint is
    down, repeatedly" arrives in. `CollectionRunService._collect_platform` catches this and
    marks the platform `UNAVAILABLE`; nothing here depends on a transport or a vendor
    payload."""

    def __init__(self, *, working: set[Platform], failing: set[Platform]) -> None:
        self._working = working
        self._failing = failing
        self.calls: list[Platform] = []

    async def fetch(
        self,
        platform: Platform,
        query: str,
        *,
        page: str | None = None,
        limit: int,
        window: CollectionWindow | None = None,
    ) -> CollectionPage:
        self.calls.append(platform)
        if platform in self._failing:
            raise ServiceUnavailableError(f"{platform}'s endpoint is down")
        endpoint = get_endpoint(_ENDPOINT_KEY_BY_PLATFORM[platform])
        assert endpoint is not None
        external_id = f"{platform.value}-{len(self.calls)}"
        return CollectionPage(
            platform=platform,
            endpoint=endpoint,
            adapter_version="test",
            items=[
                CollectedItem(
                    raw_payload={"id": external_id},
                    external_id=external_id,
                    mention=NormalizedMention(
                        platform=platform,
                        external_id=external_id,
                        text="a post",
                        posted_at=datetime.now(UTC),
                        author_handle="someuser",
                        author_display_name="Some User",
                    ),
                )
            ],
        )


class _TogglingSource(CollectionSource):
    """Succeeds for every platform in `working`, always. For a single designated
    `platform`, follows the caller's own `fail()` / `succeed()` calls: whichever was called
    most recently decides every fetch to that platform until the other is called again.

    `_PerPlatformSource` fixes a platform's fate for the source's whole lifetime, which is
    right for "Instagram is down all cycle" but cannot express "down, then recovers, then
    down again" across several cycles of the *same* service — the shape the alert-fires-
    again-on-a-fresh-crossing property needs. One call to `fetch` per platform is enough to
    decide a cycle's outcome for it (`CollectionRunService._collect_platform` returns on the
    first `ServiceUnavailableError`), so toggling between cycles, not between calls, is all
    this needs to do.
    """

    def __init__(self, *, working: set[Platform], platform: Platform) -> None:
        self._working = working
        self._platform = platform
        self._platform_failing = True
        self.calls: list[Platform] = []

    def fail(self) -> None:
        self._platform_failing = True

    def succeed(self) -> None:
        self._platform_failing = False

    async def fetch(
        self,
        platform: Platform,
        query: str,
        *,
        page: str | None = None,
        limit: int,
        window: CollectionWindow | None = None,
    ) -> CollectionPage:
        self.calls.append(platform)
        if platform == self._platform:
            if self._platform_failing:
                raise ServiceUnavailableError(f"{platform}'s endpoint is down")
        elif platform not in self._working:
            raise ServiceUnavailableError(f"{platform}'s endpoint is down")
        endpoint = get_endpoint(_ENDPOINT_KEY_BY_PLATFORM[platform])
        assert endpoint is not None
        external_id = f"{platform.value}-{len(self.calls)}"
        return CollectionPage(
            platform=platform,
            endpoint=endpoint,
            adapter_version="test",
            items=[
                CollectedItem(
                    raw_payload={"id": external_id},
                    external_id=external_id,
                    mention=NormalizedMention(
                        platform=platform,
                        external_id=external_id,
                        text="a post",
                        posted_at=datetime.now(UTC),
                        author_handle="someuser",
                        author_display_name="Some User",
                    ),
                )
            ],
        )


class _RecordingAlerter(CollectionHealthAlerter):
    """Records every alert it is asked to raise, and optionally fails the way a down paging
    integration would — the seam the Notes' claim and the alerting boundary tests exercise
    without a real alerting backend."""

    def __init__(self, *, raises: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raises = raises

    async def platform_repeatedly_failing(
        self,
        *,
        title_id: uuid.UUID,
        platform: Platform,
        consecutive_failures: int,
        reason: str | None,
    ) -> None:
        self.calls.append(
            {
                "title_id": title_id,
                "platform": platform,
                "consecutive_failures": consecutive_failures,
                "reason": reason,
            }
        )
        if self._raises:
            raise RuntimeError("paging backend unreachable")


class _RaisesForOnePlatformAlerter(CollectionHealthAlerter):
    """Records every alert attempt, then raises for exactly one designated platform — the
    shape a shared upstream outage produces when several platforms cross their threshold on
    the same cycle and the paging call for one of them blows up. Unlike `_RecordingAlerter`
    (which raises for every call or none), this lets a test prove the *other* platforms in
    the same cycle were still attempted after the raise (test round 3, FINDING A)."""

    def __init__(self, *, raises_for: Platform) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raises_for = raises_for

    async def platform_repeatedly_failing(
        self,
        *,
        title_id: uuid.UUID,
        platform: Platform,
        consecutive_failures: int,
        reason: str | None,
    ) -> None:
        self.calls.append(
            {
                "title_id": title_id,
                "platform": platform,
                "consecutive_failures": consecutive_failures,
                "reason": reason,
            }
        )
        if platform == self._raises_for:
            raise RuntimeError(f"paging backend unreachable for {platform}")


def _build_run_service(
    session: AsyncSession,
    source: CollectionSource,
    *,
    settings: Settings,
    cadence: CadencePolicy,
    alerter: CollectionHealthAlerter | None = None,
) -> CollectionRunService:
    collection_service = CollectionService(session, source)
    schedule_service = CollectionScheduleService(session, cadence)
    return CollectionRunService(
        session, collection_service, schedule_service, UnrestrictedSpendPolicy(), settings, alerter
    )


async def _pending_run(session: AsyncSession, title_id: uuid.UUID) -> Any:
    run = await CollectionRunRepository(session).next_pending_for_title(title_id)
    assert run is not None, "expected a pending collection run for this title"
    return run


def _by_platform(platforms: tuple[PlatformHealth, ...]) -> dict[str, PlatformHealth]:
    return {platform_health.platform: platform_health for platform_health in platforms}


# ---------------------------------------------------------------------------
# Section 1 — Given: my title collects from X, Reddit, YouTube, and Instagram.
# ---------------------------------------------------------------------------


async def test_given_a_title_collecting_from_all_four_platforms_has_one_health_entry_each(
    db_session: AsyncSession,
) -> None:
    """Every configured platform gets a health entry, in the configured order, before a
    single cycle has ever run — a platform that has never been attempted is exactly the one
    worth showing (`CollectionHealthService.health_for_title`'s own docstring), and driving
    the list off the results table instead would make it invisible by being absent."""
    title = await _build_title(db_session, slug="sun-pictures-all-four-platforms")
    service = CollectionHealthService(db_session, FixedCadencePolicy(12), _settings())

    health = await service.health_for_title(title)

    assert [platform_health.platform for platform_health in health.platforms] == [
        str(platform) for platform in ALL_FOUR_PLATFORMS
    ]
    assert all(
        platform_health.state is PlatformHealthState.PENDING for platform_health in health.platforms
    )


# ---------------------------------------------------------------------------
# Section 2 — Given: the dashboard header shows a per-platform last-successful-collection
# time.
# ---------------------------------------------------------------------------


async def test_given_the_dashboard_shows_each_platforms_last_successful_collection_time(
    db_session: AsyncSession,
) -> None:
    """Two platforms, two distinct success times, and — on top of X's — a *later* failed
    attempt. The header must read the last success, not the last attempt: a poll that fails
    after a platform has been healthy for hours must not blank out the time that platform
    last actually worked."""
    cadence = FixedCadencePolicy(12)  # 2h interval, 4h stale boundary at the default tolerance.
    title = await _build_title(db_session, slug="sun-pictures-last-success-time")
    run_id = await _any_run_id(db_session, title, cadence)

    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    x_success_at = now - timedelta(hours=2)
    x_failure_at = now - timedelta(minutes=5)
    reddit_success_at = now - timedelta(hours=3, minutes=30)

    db_session.add_all(
        [
            _platform_result(
                run_id=run_id,
                title_id=title.id,
                platform=Platform.X,
                status=PlatformCollectionStatus.SUCCEEDED,
                finished_at=x_success_at,
            ),
            _platform_result(
                run_id=run_id,
                title_id=title.id,
                platform=Platform.X,
                status=PlatformCollectionStatus.FAILED,
                finished_at=x_failure_at,
                failure_reason="a transient timeout",
            ),
            _platform_result(
                run_id=run_id,
                title_id=title.id,
                platform=Platform.REDDIT,
                status=PlatformCollectionStatus.SUCCEEDED,
                finished_at=reddit_success_at,
            ),
        ]
    )
    await db_session.flush()

    service = CollectionHealthService(db_session, cadence, _settings())
    health = await service.health_for_title(title, now=now)

    by_platform = _by_platform(health.platforms)
    assert by_platform[str(Platform.X)].last_successful_at == x_success_at
    assert by_platform[str(Platform.REDDIT)].last_successful_at == reddit_success_at


# ---------------------------------------------------------------------------
# Section 3 — Given: a platform is considered stale when it has missed the expected
# interval for its current cadence phase. The task brief's own candidate: the single most
# likely thing to be wrong.
# ---------------------------------------------------------------------------


async def test_given_a_platform_is_stale_relative_to_its_current_cadence_phase(
    db_session: AsyncSession,
) -> None:
    """The identical last-success time and the identical silence (90 minutes), judged
    against two different cadence phases, must disagree.

    Release surge (48/day) implies a 30-minute interval — a 60-minute stale boundary at the
    default 2.0 tolerance — so 90 minutes of silence is well past it: stale. Dormant (2/day)
    implies a 12-hour interval — a 24-hour boundary — so the same 90 minutes is ordinary:
    reporting. A test that checked only one phase could pass with the interval hardcoded or
    ignored entirely; checking both against the same inputs is what actually pins "current
    cadence phase" rather than "some cadence phase".
    """
    surge_cadence = FixedCadencePolicy(48)
    dormant_cadence = FixedCadencePolicy(2)
    surge_title = await _build_title(db_session, slug="sun-pictures-surge-staleness")
    dormant_title = await _build_title(db_session, slug="sun-pictures-dormant-staleness")

    last_success_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    now = last_success_at + timedelta(minutes=90)

    for title, cadence in ((surge_title, surge_cadence), (dormant_title, dormant_cadence)):
        run_id = await _any_run_id(db_session, title, cadence)
        db_session.add(
            _platform_result(
                run_id=run_id,
                title_id=title.id,
                platform=Platform.X,
                status=PlatformCollectionStatus.SUCCEEDED,
                finished_at=last_success_at,
            )
        )
    await db_session.flush()

    surge_health = await CollectionHealthService(
        db_session, surge_cadence, _settings()
    ).health_for_title(surge_title, now=now)
    dormant_health = await CollectionHealthService(
        db_session, dormant_cadence, _settings()
    ).health_for_title(dormant_title, now=now)

    surge_x = next(p for p in surge_health.platforms if p.platform == str(Platform.X))
    dormant_x = next(p for p in dormant_health.platforms if p.platform == str(Platform.X))
    assert surge_x.state is PlatformHealthState.STALE
    assert dormant_x.state is PlatformHealthState.REPORTING


# ---------------------------------------------------------------------------
# Section 4 — Given: stale platforms are excluded from "as of" freshness claims.
# ---------------------------------------------------------------------------


async def test_given_stale_platforms_are_excluded_from_the_as_of_freshness_claim(
    db_session: AsyncSession,
) -> None:
    """Reddit last succeeded two days ago and has failed ever since — clearly stale at a
    4-hour boundary. X succeeded ten minutes ago. A freshness claim built by taking the
    oldest success over *every* platform, stale or not, would answer with Reddit's two-day-
    old timestamp; the correct claim comes only from X, the platform actually reporting.
    """
    cadence = FixedCadencePolicy(12)  # 4h stale boundary at the default tolerance.
    title = await _build_title(db_session, slug="sun-pictures-freshness-exclusion")
    run_id = await _any_run_id(db_session, title, cadence)

    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    x_success_at = now - timedelta(minutes=10)
    reddit_old_success_at = now - timedelta(days=2)
    reddit_recent_failure_at = now - timedelta(hours=1)

    db_session.add_all(
        [
            _platform_result(
                run_id=run_id,
                title_id=title.id,
                platform=Platform.X,
                status=PlatformCollectionStatus.SUCCEEDED,
                finished_at=x_success_at,
            ),
            _platform_result(
                run_id=run_id,
                title_id=title.id,
                platform=Platform.REDDIT,
                status=PlatformCollectionStatus.SUCCEEDED,
                finished_at=reddit_old_success_at,
            ),
            _platform_result(
                run_id=run_id,
                title_id=title.id,
                platform=Platform.REDDIT,
                status=PlatformCollectionStatus.FAILED,
                finished_at=reddit_recent_failure_at,
                failure_reason="endpoint refused the request",
            ),
        ]
    )
    await db_session.flush()

    health = await CollectionHealthService(db_session, cadence, _settings()).health_for_title(
        title, now=now
    )

    reddit = next(p for p in health.platforms if p.platform == str(Platform.REDDIT))
    assert reddit.state is PlatformHealthState.STALE
    assert health.data_as_of == x_success_at
    assert health.data_as_of != reddit_old_success_at


# ---------------------------------------------------------------------------
# Section 5 — When: Instagram collection fails repeatedly through the surge window.
# ---------------------------------------------------------------------------


async def test_when_instagram_fails_repeatedly_every_cycle_records_it_unavailable(
    db_session: AsyncSession,
) -> None:
    """Three real cycles through `CollectionRunService`, at surge cadence, with Instagram
    refusing every single time while X, Reddit, and YouTube keep working. Failure is
    per-platform, not per-cycle (E03-S01's own rule): every cycle must still succeed
    overall, and every one of Instagram's three attempts must be recorded, not merely the
    first."""
    cadence = FixedCadencePolicy(48)
    settings = _settings()
    source = _PerPlatformSource(
        working={Platform.X, Platform.REDDIT, Platform.YOUTUBE}, failing={Platform.INSTAGRAM}
    )
    title = await _title_with_first_run(db_session, cadence, slug="sun-pictures-instagram-repeats")
    service = _build_run_service(db_session, source, settings=settings, cadence=cadence)

    for _ in range(3):
        result = await service.execute_run(await _pending_run(db_session, title.id))
        assert result.status is CollectionRunStatus.SUCCEEDED

    result_repository = CollectionPlatformResultRepository(db_session)
    instagram_attempts = await result_repository.recent_for_platform(
        title.id, Platform.INSTAGRAM, limit=10
    )
    x_attempts = await result_repository.recent_for_platform(title.id, Platform.X, limit=10)

    assert len(instagram_attempts) == 3
    assert all(
        attempt.status is PlatformCollectionStatus.UNAVAILABLE for attempt in instagram_attempts
    )
    assert len(x_attempts) == 3
    assert all(attempt.status is PlatformCollectionStatus.SUCCEEDED for attempt in x_attempts)


# ---------------------------------------------------------------------------
# Section 6 — Then: the dashboard shows Instagram as stale with its last successful time,
# and every chart containing Instagram data carries a visible warning.
# ---------------------------------------------------------------------------


async def test_then_instagram_shows_stale_with_its_last_success_others_keep_reporting(
    db_session: AsyncSession,
) -> None:
    """The scenario's own ending, assembled directly: Instagram last succeeded, then failed
    repeatedly through the surge window and has now missed its cadence-phase interval by a
    wide margin, while X, Reddit, and YouTube kept reporting throughout. The backend half of
    "every chart carries a visible warning" is `PlatformHealthState.STALE` surviving to this
    read, next to the other three still `REPORTING` — the fact a chart renders its warning
    from. Rendering the warning itself is frontend work, untested here (see the module
    docstring)."""
    cadence = FixedCadencePolicy(48)  # 30-minute interval, 60-minute stale boundary.
    title = await _build_title(db_session, slug="sun-pictures-then-clause")
    run_id = await _any_run_id(db_session, title, cadence)

    instagram_last_success_at = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)
    now = instagram_last_success_at + timedelta(minutes=90)
    others_last_success_at = now - timedelta(minutes=5)

    rows = [
        _platform_result(
            run_id=run_id,
            title_id=title.id,
            platform=Platform.INSTAGRAM,
            status=PlatformCollectionStatus.SUCCEEDED,
            finished_at=instagram_last_success_at,
        ),
    ]
    for offset_minutes in (10, 20, 30):
        rows.append(
            _platform_result(
                run_id=run_id,
                title_id=title.id,
                platform=Platform.INSTAGRAM,
                status=PlatformCollectionStatus.UNAVAILABLE,
                finished_at=instagram_last_success_at + timedelta(minutes=offset_minutes),
                failure_reason="Instagram's endpoint is down",
            )
        )
    for platform in (Platform.X, Platform.REDDIT, Platform.YOUTUBE):
        rows.append(
            _platform_result(
                run_id=run_id,
                title_id=title.id,
                platform=platform,
                status=PlatformCollectionStatus.SUCCEEDED,
                finished_at=others_last_success_at,
            )
        )
    db_session.add_all(rows)
    await db_session.flush()

    health = await CollectionHealthService(db_session, cadence, _settings()).health_for_title(
        title, now=now
    )
    by_platform = _by_platform(health.platforms)

    instagram = by_platform[str(Platform.INSTAGRAM)]
    assert instagram.state is PlatformHealthState.STALE
    assert instagram.last_successful_at == instagram_last_success_at

    for platform in (Platform.X, Platform.REDDIT, Platform.YOUTUBE):
        assert by_platform[str(platform)].state is PlatformHealthState.REPORTING

    assert health.stale_platforms == (instagram,)
    assert health.data_as_of == others_last_success_at


# ---------------------------------------------------------------------------
# Section 7 — Notes: repeated failures should raise an internal alert to data ops before
# the customer notices.
# ---------------------------------------------------------------------------


async def test_notes_repeated_platform_failures_raise_an_internal_alert_to_data_ops(
    db_session: AsyncSession,
) -> None:
    """The Notes' own claim, not in the Gherkin. Instagram fails on every one of three
    cycles (the default alert threshold); by the third, data ops must have been told,
    without anybody having opened a dashboard — the alert fires from the cycle that crossed
    the threshold, not from a screen nobody is looking at."""
    cadence = FixedCadencePolicy(48)
    settings = _settings()  # collection_platform_failure_alert_threshold defaults to 3.
    source = _PerPlatformSource(
        working={Platform.X, Platform.REDDIT, Platform.YOUTUBE}, failing={Platform.INSTAGRAM}
    )
    alerter = _RecordingAlerter()
    title = await _title_with_first_run(db_session, cadence, slug="sun-pictures-alert-notes")
    service = _build_run_service(
        db_session, source, settings=settings, cadence=cadence, alerter=alerter
    )

    for _ in range(3):
        await service.execute_run(await _pending_run(db_session, title.id))

    assert len(alerter.calls) == 1
    call = alerter.calls[0]
    assert call["platform"] is Platform.INSTAGRAM
    assert call["consecutive_failures"] == 3
    assert call["reason"] == "instagram's endpoint is down"


# ---------------------------------------------------------------------------
# Section 8 — Extra: freshness_as_of is the oldest reporting success, never the newest, and
# null when nothing is reporting.
# ---------------------------------------------------------------------------


def test_freshness_as_of_is_the_oldest_reporting_success_not_the_newest_and_null_with_nothing_reporting() -> (  # noqa: E501
    None
):
    """A pure-function test of `freshness_as_of` itself, deliberately built so a
    max()-instead-of-min() bug cannot pass by accident: three reporting platforms with
    widely separated success times, where "oldest" and "newest" give visibly different
    answers, plus the all-stale case, which must be null rather than an invented
    timestamp."""
    oldest = datetime(2026, 8, 14, 6, 0, tzinfo=UTC)
    middle = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
    newest = datetime(2026, 8, 14, 11, 30, tzinfo=UTC)
    healths = [
        PlatformHealth(
            platform="x",
            state=PlatformHealthState.REPORTING,
            last_successful_at=newest,
            last_failure_reason=None,
            consecutive_failures=0,
        ),
        PlatformHealth(
            platform="reddit",
            state=PlatformHealthState.REPORTING,
            last_successful_at=oldest,
            last_failure_reason=None,
            consecutive_failures=0,
        ),
        PlatformHealth(
            platform="youtube",
            state=PlatformHealthState.REPORTING,
            last_successful_at=middle,
            last_failure_reason=None,
            consecutive_failures=0,
        ),
    ]

    assert freshness_as_of(healths) == oldest
    assert freshness_as_of(healths) != newest

    all_stale_or_pending = [
        PlatformHealth(
            platform="instagram",
            state=PlatformHealthState.STALE,
            last_successful_at=oldest,
            last_failure_reason="down",
            consecutive_failures=5,
        ),
        PlatformHealth(
            platform="reddit",
            state=PlatformHealthState.PENDING,
            last_successful_at=None,
            last_failure_reason=None,
            consecutive_failures=0,
        ),
    ]
    assert freshness_as_of(all_stale_or_pending) is None


# ---------------------------------------------------------------------------
# Section 9 — Extra: pending vs. stale. A brand-new title shows no stale platforms; an
# attempted, never-successful platform shows stale immediately.
# ---------------------------------------------------------------------------


async def test_a_brand_new_title_has_no_stale_platforms_but_an_attempted_never_succeeded_platform_is_stale(  # noqa: E501
    db_session: AsyncSession,
) -> None:
    """A title a minute old must not greet its owner with a stale warning — nothing has had
    a chance to run yet, which is `PENDING`, not `STALE`. A platform that has been tried and
    has never once succeeded is the opposite case: `STALE` immediately, however recently it
    was tried, because a platform that answers and never once works is exactly the "not
    currently reporting" sentence the story asks the dashboard to say."""
    cadence = FixedCadencePolicy(12)
    settings = _settings()
    brand_new_title = await _build_title(db_session, slug="sun-pictures-brand-new")

    brand_new_health = await CollectionHealthService(
        db_session, cadence, settings
    ).health_for_title(brand_new_title)
    assert brand_new_health.has_stale_platform is False
    assert all(p.state is PlatformHealthState.PENDING for p in brand_new_health.platforms)

    misconfigured_title = await _build_title(db_session, slug="sun-pictures-misconfigured")
    run_id = await _any_run_id(db_session, misconfigured_title, cadence)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    db_session.add(
        _platform_result(
            run_id=run_id,
            title_id=misconfigured_title.id,
            platform=Platform.INSTAGRAM,
            status=PlatformCollectionStatus.FAILED,
            finished_at=now - timedelta(seconds=30),  # Tried moments ago, not stale by age.
            failure_reason="no adapter for this endpoint",
        )
    )
    await db_session.flush()

    misconfigured_health = await CollectionHealthService(
        db_session, cadence, settings
    ).health_for_title(misconfigured_title, now=now)
    instagram = next(
        p for p in misconfigured_health.platforms if p.platform == str(Platform.INSTAGRAM)
    )
    assert instagram.state is PlatformHealthState.STALE
    assert instagram.last_successful_at is None


# ---------------------------------------------------------------------------
# Section 10 — Extra: `finished_at` comes back naive from SQLite and must still compare
# correctly against a fresh, aware `now`. This defect class has bitten this epic twice
# already (E03-S03, E03-S04).
# ---------------------------------------------------------------------------


async def test_a_platforms_finished_at_read_back_naive_from_sqlite_still_compares_correctly_against_aware_now(  # noqa: E501
    db_session: AsyncSession,
) -> None:
    """Pins the premise and the fix in one test. `CollectionPlatformResultRepository`'s
    grouped query goes straight through the SQL layer rather than the ORM identity map, so
    SQLite's own naive round trip is genuinely exercised here, not merely trusted to
    happen. Without `as_utc` reconciling the two in `CollectionHealthService`, comparing a
    naive `last_successful_at` against an aware `now` raises `TypeError` from inside
    `staleness_deadline` before a verdict is ever reached."""
    cadence = FixedCadencePolicy(12)
    title = await _build_title(db_session, slug="sun-pictures-naive-datetime")
    run_id = await _any_run_id(db_session, title, cadence)

    aware_success_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    db_session.add(
        _platform_result(
            run_id=run_id,
            title_id=title.id,
            platform=Platform.X,
            status=PlatformCollectionStatus.SUCCEEDED,
            finished_at=aware_success_at,
        )
    )
    await db_session.flush()

    # The premise: SQLite hands this back with no tzinfo, whatever went in.
    raw = await CollectionPlatformResultRepository(db_session).last_success_at_by_platform(title.id)
    assert raw[Platform.X].tzinfo is None

    # The fix: `CollectionHealthService` still gets the right, correctly-compared answer.
    now = aware_success_at + timedelta(hours=1)  # Within the 4h boundary: still reporting.
    health = await CollectionHealthService(db_session, cadence, _settings()).health_for_title(
        title, now=now
    )
    x = next(p for p in health.platforms if p.platform == str(Platform.X))
    assert x.state is PlatformHealthState.REPORTING
    assert x.last_successful_at == aware_success_at


# ---------------------------------------------------------------------------
# Section 11 — Extra: consecutive_failures counts only the leading run of failures, and its
# reason comes from that leading run, not an older outage.
# ---------------------------------------------------------------------------


async def test_consecutive_failures_counts_only_the_leading_run_and_its_reason_not_an_older_outage(
    db_session: AsyncSession,
) -> None:
    """Failed, recovered, failed once more: one failure deep with today's reason, not three
    deep with last week's. Reading the reason off the whole window instead of the leading
    run would report an outage that already recovered as the current problem, sending
    somebody to fix the wrong thing."""
    cadence = FixedCadencePolicy(12)
    title = await _build_title(db_session, slug="sun-pictures-leading-run")
    run_id = await _any_run_id(db_session, title, cadence)

    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    rows = [
        _platform_result(
            run_id=run_id,
            title_id=title.id,
            platform=Platform.REDDIT,
            status=PlatformCollectionStatus.FAILED,
            finished_at=now - timedelta(days=7),
            failure_reason="last week's outage",
        ),
        _platform_result(
            run_id=run_id,
            title_id=title.id,
            platform=Platform.REDDIT,
            status=PlatformCollectionStatus.SUCCEEDED,
            finished_at=now - timedelta(days=6),
        ),
        _platform_result(
            run_id=run_id,
            title_id=title.id,
            platform=Platform.REDDIT,
            status=PlatformCollectionStatus.FAILED,
            finished_at=now - timedelta(minutes=10),
            failure_reason="today's blip",
        ),
    ]
    db_session.add_all(rows)
    await db_session.flush()

    health = await CollectionHealthService(db_session, cadence, _settings()).health_for_title(
        title, now=now
    )
    reddit = next(p for p in health.platforms if p.platform == str(Platform.REDDIT))

    assert reddit.consecutive_failures == 1
    assert reddit.last_failure_reason == "today's blip"


# ---------------------------------------------------------------------------
# Section 12 — Extra: an alert fires exactly at the threshold, never below it, and an
# alerter that raises cannot fail the cycle it is reporting on.
# ---------------------------------------------------------------------------


async def test_an_alert_fires_exactly_at_the_threshold_not_below_it_and_a_raising_alerter_cannot_fail_the_cycle(  # noqa: E501
    db_session: AsyncSession,
) -> None:
    """Two cycles of failure must raise nothing; the third, crossing the default threshold
    of 3, must raise exactly one alert.

    The safety property — a paging integration that is itself down must not turn a working
    poll into a failed one — is proven in its own scenario and its own title, with the
    raising alerter in place from the start. It has to be the alerter present *on the cycle
    that crosses the threshold*, because that is the only cycle `_alert_on_repeated_failures`
    ever calls the alerter from (E03-S05-test-round-2, FINDING 1): the fix that makes the
    first half of this test true — the alert going quiet past the threshold instead of
    firing on every subsequent cycle — is exactly what would make a raising alerter placed on
    a *fourth* cycle never be invoked at all, silently proving nothing. So this half also
    runs three cycles, on a title of its own, with the raising alerter present throughout.
    """
    cadence = FixedCadencePolicy(12)
    settings = _settings()
    source = _PerPlatformSource(working={Platform.X}, failing={Platform.INSTAGRAM})
    title = await _title_with_first_run(db_session, cadence, slug="sun-pictures-alert-boundary")

    recording_alerter = _RecordingAlerter()
    service = _build_run_service(
        db_session, source, settings=settings, cadence=cadence, alerter=recording_alerter
    )

    first = await service.execute_run(await _pending_run(db_session, title.id))
    assert first.status is CollectionRunStatus.SUCCEEDED
    assert recording_alerter.calls == []  # 1 consecutive failure, below the threshold of 3.

    second = await service.execute_run(await _pending_run(db_session, title.id))
    assert second.status is CollectionRunStatus.SUCCEEDED
    assert recording_alerter.calls == []  # 2 consecutive failures, still below the threshold.

    third = await service.execute_run(await _pending_run(db_session, title.id))
    assert third.status is CollectionRunStatus.SUCCEEDED
    assert len(recording_alerter.calls) == 1  # Exactly the threshold: fires exactly once.
    assert recording_alerter.calls[0]["consecutive_failures"] == 3

    # A raising alerter, present from the first cycle of its own title, so it is genuinely
    # in place on the one cycle — the crossing — that ever invokes it.
    raising_source = _PerPlatformSource(working={Platform.X}, failing={Platform.INSTAGRAM})
    raising_alerter = _RecordingAlerter(raises=True)
    raising_title = await _title_with_first_run(
        db_session, cadence, slug="sun-pictures-alerter-raises"
    )
    raising_service = _build_run_service(
        db_session, raising_source, settings=settings, cadence=cadence, alerter=raising_alerter
    )

    for _ in range(2):
        cycle = await raising_service.execute_run(await _pending_run(db_session, raising_title.id))
        assert cycle.status is CollectionRunStatus.SUCCEEDED
    assert raising_alerter.calls == []  # Not yet crossed: the raising alerter is untouched.

    third_of_raising = await raising_service.execute_run(
        await _pending_run(db_session, raising_title.id)
    )

    # The alerter raised on the crossing cycle, and the cycle it was reporting on must not
    # have failed because of it: X still succeeded, so the cycle is still SUCCEEDED.
    assert third_of_raising.status is CollectionRunStatus.SUCCEEDED
    assert len(raising_alerter.calls) == 1
    assert raising_alerter.calls[0]["consecutive_failures"] == 3


# ---------------------------------------------------------------------------
# Section 13 — Extra (pure-function sanity): health_state_for's own two-way split.
# ---------------------------------------------------------------------------


def test_health_state_for_splits_never_attempted_pending_from_never_succeeded_stale() -> None:
    """A direct, database-free pin of the same split Section 9 exercises through the
    service, so a mistake in `health_state_for` itself — not merely in how the service
    calls it — has a test that isolates it."""
    interval = timedelta(hours=2)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    never_attempted = health_state_for(
        last_successful_at=None,
        has_been_attempted=False,
        interval=interval,
        tolerance=2.0,
        now=now,
    )
    attempted_never_succeeded = health_state_for(
        last_successful_at=None,
        has_been_attempted=True,
        interval=interval,
        tolerance=2.0,
        now=now,
    )

    assert never_attempted is PlatformHealthState.PENDING
    assert attempted_never_succeeded is PlatformHealthState.STALE


# ---------------------------------------------------------------------------
# Section 14 — Test round 2: the alert-fatigue fix (FINDING 1) and the duplicated-cadence-
# decision fix (FINDING 2).
# ---------------------------------------------------------------------------


async def test_an_alert_does_not_fire_again_on_the_fourth_or_fifth_consecutive_failure(
    db_session: AsyncSession,
) -> None:
    """The defect FINDING 1 actually fixed, pinned directly: before the fix,
    `_alert_on_repeated_failures` fired on *every* cycle once a platform crossed the
    threshold, so at release-surge cadence a known-broken platform would page data ops 48
    times a day. Five consecutive failing cycles must still leave exactly one alert on
    record — the one that fired when the threshold was crossed on the third — with nothing
    added by the fourth or fifth."""
    cadence = FixedCadencePolicy(12)
    settings = _settings()
    source = _PerPlatformSource(working={Platform.X}, failing={Platform.INSTAGRAM})
    title = await _title_with_first_run(db_session, cadence, slug="sun-pictures-no-refire")
    alerter = _RecordingAlerter()
    service = _build_run_service(
        db_session, source, settings=settings, cadence=cadence, alerter=alerter
    )

    for _ in range(5):
        result = await service.execute_run(await _pending_run(db_session, title.id))
        assert result.status is CollectionRunStatus.SUCCEEDED

    assert len(alerter.calls) == 1
    assert alerter.calls[0]["consecutive_failures"] == 3


async def test_a_platform_that_recovers_then_fails_to_the_threshold_again_alerts_a_second_time(
    db_session: AsyncSession,
) -> None:
    """The counterpart property to the one above, and just as load-bearing: suppression must
    not turn into "only ever alert once". Instagram fails three cycles running (alerting
    once), recovers for one cycle (raising nothing — recovery is not an incident), then
    fails three cycles running again. The second run crosses the threshold afresh and must
    alert again, because it is a genuinely new incident, not a continuation of the first."""
    cadence = FixedCadencePolicy(12)
    settings = _settings()
    source = _TogglingSource(
        working={Platform.X, Platform.REDDIT, Platform.YOUTUBE}, platform=Platform.INSTAGRAM
    )  # starts failing
    title = await _title_with_first_run(db_session, cadence, slug="sun-pictures-alerts-again")
    alerter = _RecordingAlerter()
    service = _build_run_service(
        db_session, source, settings=settings, cadence=cadence, alerter=alerter
    )

    for _ in range(3):
        result = await service.execute_run(await _pending_run(db_session, title.id))
        assert result.status is CollectionRunStatus.SUCCEEDED
    assert len(alerter.calls) == 1
    assert alerter.calls[0]["consecutive_failures"] == 3

    source.succeed()
    recovered = await service.execute_run(await _pending_run(db_session, title.id))
    assert recovered.status is CollectionRunStatus.SUCCEEDED
    assert len(alerter.calls) == 1  # Recovery itself raises nothing.

    source.fail()
    for _ in range(3):
        result = await service.execute_run(await _pending_run(db_session, title.id))
        assert result.status is CollectionRunStatus.SUCCEEDED

    assert len(alerter.calls) == 2  # A fresh crossing: a second, distinct alert.
    assert alerter.calls[1]["consecutive_failures"] == 3


async def test_health_for_title_honours_a_passed_in_cadence_decision_rather_than_re_deriving_one(
    db_session: AsyncSession,
) -> None:
    """`CollectionHealthService` is constructed with a dormant-rate policy
    (`FixedCadencePolicy(12)`: a 2h interval, a 4h stale boundary), so if `health_for_title`
    quietly ignored the `cadence` decision it was handed and re-derived its own, 90 minutes
    of silence would read as `REPORTING`. Passing a decision that implies release-surge's
    30-minute interval (a 60-minute stale boundary) instead must make that same 90 minutes
    of silence `STALE`. Only the passed-in decision — not the policy the service was built
    with — can produce that answer, so this pins that `CollectionStatusService`'s already-
    computed decision (FINDING 2) is genuinely used, not merely accepted and discarded."""
    dormant_cadence = FixedCadencePolicy(12)
    title = await _build_title(db_session, slug="sun-pictures-passed-cadence")
    run_id = await _any_run_id(db_session, title, dormant_cadence)

    last_success_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
    now = last_success_at + timedelta(minutes=90)
    db_session.add(
        _platform_result(
            run_id=run_id,
            title_id=title.id,
            platform=Platform.X,
            status=PlatformCollectionStatus.SUCCEEDED,
            finished_at=last_success_at,
        )
    )
    await db_session.flush()

    service = CollectionHealthService(db_session, dormant_cadence, _settings())

    # No decision passed: the service asks its own dormant-rate policy directly, whose 4h
    # boundary makes 90 minutes of silence ordinary.
    undecided = await service.health_for_title(title, now=now)
    x_undecided = next(p for p in undecided.platforms if p.platform == str(Platform.X))
    assert x_undecided.state is PlatformHealthState.REPORTING

    # A decision passed in, implying a rate the service was never constructed with. If it
    # were ignored, the answer above would repeat; it must not.
    surge_decision = CadenceDecision(
        phase=CadencePhase.RELEASE_SURGE,
        calendar_phase=CadencePhase.RELEASE_SURGE,
        polls_per_day=48,
        is_volume_escalated=False,
    )
    decided = await service.health_for_title(title, now=now, cadence=surge_decision)
    x_decided = next(p for p in decided.platforms if p.platform == str(Platform.X))
    assert x_decided.state is PlatformHealthState.STALE


# ---------------------------------------------------------------------------
# Section 15 — Test round 3: per-platform alert isolation (FINDING A) and the config
# validator that refuses a failure window that can never reach its alert threshold
# (FINDING B).
# ---------------------------------------------------------------------------


async def test_a_raising_alerter_for_one_platform_does_not_stop_the_others_in_the_same_cycle(
    db_session: AsyncSession,
) -> None:
    """FINDING A: a shared upstream outage that takes Reddit, YouTube, and Instagram down
    together, all crossing the alert threshold on the very same cycle, with an alerter that
    blows up for Reddit specifically. Reddit is iterated first among the failing platforms
    (`collection_platforms` is `[X, Reddit, YouTube, Instagram]`, and X is the one platform
    still succeeding here), so a `try/except` wrapped around the *whole* `for platform in
    failing` loop — rather than around each iteration — would let Reddit's raise abort the
    loop before YouTube or Instagram were ever attempted. Both must still be attempted, and
    the cycle itself — already closed and committed before alerting runs — must still read
    as `SUCCEEDED`, because X kept collecting throughout.

    The alert threshold is set to 1 so a single cycle is enough to cross it for every
    platform that fails in it; nothing about the bug this test targets depends on how many
    cycles it took to reach the threshold, only on what happens once several platforms cross
    it in the same one.
    """
    cadence = FixedCadencePolicy(48)
    settings = _settings(collection_platform_failure_alert_threshold=1)
    source = _PerPlatformSource(
        working={Platform.X}, failing={Platform.REDDIT, Platform.YOUTUBE, Platform.INSTAGRAM}
    )
    alerter = _RaisesForOnePlatformAlerter(raises_for=Platform.REDDIT)
    title = await _title_with_first_run(
        db_session, cadence, slug="sun-pictures-alert-isolation"
    )
    service = _build_run_service(
        db_session, source, settings=settings, cadence=cadence, alerter=alerter
    )

    result = await service.execute_run(await _pending_run(db_session, title.id))

    assert result.status is CollectionRunStatus.SUCCEEDED

    attempted_platforms = {call["platform"] for call in alerter.calls}
    assert attempted_platforms == {Platform.REDDIT, Platform.YOUTUBE, Platform.INSTAGRAM}
    assert all(call["consecutive_failures"] == 1 for call in alerter.calls)


def test_a_failure_window_shorter_than_the_alert_threshold_is_refused_at_startup_but_a_zero_threshold_is_always_accepted() -> (  # noqa: E501
    None
):
    """FINDING B: `consecutive_failures` reads at most `collection_platform_failure_window`
    rows, so a window smaller than the alert threshold caps the count below the value it
    would need to equal — no alert can ever fire, while staleness reporting keeps working
    perfectly, which is the worst shape for this bug: the deployment looks fully
    instrumented and pages nobody. `Settings` must refuse that combination at construction.

    A threshold of 0 is the deliberate way to turn alerting off, so it must be accepted
    whatever the window is — including a window that would otherwise be too short for a
    non-zero threshold.
    """
    with pytest.raises(ValidationError):
        Settings(
            collection_platform_failure_window=2, collection_platform_failure_alert_threshold=3
        )

    # The boundary itself — window equal to threshold — must be accepted, not just anything
    # comfortably above it.
    at_the_boundary = Settings(
        collection_platform_failure_window=3, collection_platform_failure_alert_threshold=3
    )
    assert at_the_boundary.collection_platform_failure_window == 3

    # Threshold 0 (alerting off) is accepted with any window, including one far below what a
    # non-zero threshold would have required.
    alerting_off = Settings(
        collection_platform_failure_window=1, collection_platform_failure_alert_threshold=0
    )
    assert alerting_off.collection_platform_failure_alert_threshold == 0

"""Tests for E03-S02 — Poll harder during release week and back off when it's quiet.

Story: stories/E03-agentic-collection-layer/E03-S02-adaptive-cadence-by-campaign-phase.md
Epic: stories/E03-agentic-collection-layer/EPIC.md

The story has exactly one Gherkin scenario. It maps to exactly one test:

  - Scenario "A title crosses into release week and the cadence escalates on its own" ->
    `test_scenario_a_title_crosses_into_release_week_and_the_cadence_escalates_on_its_own`.
    Built against the real HTTP status endpoint (the "Title Dashboard" the AC names), with
    a title created in the campaign phase and read twice: once with the wall clock frozen
    on a campaign day, once frozen inside the surge window, with no other action taken
    between the two reads. That "no action required from me" is the point of the test, not
    an incidental property of it.

Six tests total: the one scenario, plus five chosen against risk rather than coverage.

Two are directed by the story's own Notes and the epic ledger, and are not optional:

  - `test_a_rival_insert_between_the_known_ids_read_and_the_commit_is_not_lost_or_duplicated`
    — the concurrent double-poll retry in `CollectionService._store_and_commit`, which the
    E03-S01 ledger entry records as shipped without a test and names as "the first thing
    E03-S02 should close, given it is the story where surge cadence makes overlap
    routine". Genuinely exercises the race: a second, independent session inserts one of
    the page's mentions and commits it between this writer's read of known ids and its own
    commit, and the assertion is that the rest of the page still lands and the collided
    post is not duplicated. Confirmed sensitive by hand — see the task report.

  - `test_a_dormant_title_with_no_history_at_all_escalates_on_an_unplanned_volume_spike`
    — the story's Notes: "an unplanned controversy in the dormant phase should escalate
    cadence" is not in the Gherkin and needs its own test. Built on the exact case the
    implementation's own docstring names: a title with no mention history at all, so its
    baseline is zero and anything above the floor counts as unlike anything it has done
    before.

Three are my own choices, picked for where this story is most likely to be wrong:

  - `test_phase_for_day_boundaries_are_inclusive_on_both_sides_of_every_window` — the
    calendar arithmetic the ~$273 cost model, the dashboard, and the scheduler all read
    from. An off-by-one here is silent: it never raises, it just polls at the wrong rate
    for one day at each of six boundaries.

  - `test_reconcile_pending_cadence_is_idempotent_and_never_pushes_a_run_later` — the
    docstring's own claims ("reconciling the same run on ten consecutive ticks gives the
    same answer as reconciling it once", "can only ever make a title poll sooner") are
    exactly the kind of claim that is easy to state and easy to get subtly wrong, and nothing
    in the Gherkin would catch a regression in either half.

  - `test_a_titles_baseline_is_computed_over_days_it_actually_has_not_the_configured_window`
    — `MentionVolumeReader`'s baseline arithmetic on a title with only a few days of
    history. Dividing by the configured 14-day window when only 3 days of history exist
    would understate the baseline and escalate ordinary steady volume on every new title,
    which is the opposite of "unplanned".

Naive-vs-aware datetime handling on SQLite is exercised incidentally by every test in this
file that runs against the file-backed or in-memory SQLite engines with mixed aware/naive
datetimes flowing through `as_utc`, but was not judged worth a dedicated seventh test
within budget.

Two more were added after a reviewer finding on round 1: `_is_escalated_by_volume` refused
to escalate a title already *at* surge, but not a CAMPAIGN-phase title, so a campaign
title's volume spike could walk straight to release_surge (48/day) — a 4x jump with no
calendar authority behind it, contradicting both this class's own docstring and the
story's Notes (which name only the dormant phase as volume-escalatable). The fix pins a
named ceiling, `CadencePhase.is_volume_escalatable` / `HIGHEST_VOLUME_ESCALATED_PHASE`, and
`_is_escalated_by_volume` now guards on it.

  - `test_a_campaign_phase_title_with_a_volume_spike_does_not_escalate_to_surge` — the
    regression the finding names, run through `PhaseCadencePolicy.decide` (not the enum
    predicate in isolation, which would still pass with the bug present, since the bug was
    that the policy never consulted the ceiling).

  - `test_project_campaign_cost_over_the_docstrings_six_month_window`
    `_matches_the_notes_273_per_title`
    — the reviewer's second note: nothing called `project_campaign_cost` and checked it
    against the concept note's own "~$273/title" (§7), even though that figure is what the
    escalation ceiling above exists to protect and the story's Notes name it as the thing
    any cadence change must keep in sync.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.collection_status_service as collection_status_service_module
from app.core.cadence_phase import CadencePhase, phase_for_day
from app.core.collection_endpoints import get_endpoint
from app.core.config import Settings
from app.core.platforms import Platform
from app.core.timestamps import as_utc
from app.models import Base
from app.models.collection_run import CollectionRun, CollectionRunStatus, CollectionRunTrigger
from app.models.mention import Mention
from app.models.organization import Organization, OrganizationType
from app.models.title import Title
from app.repositories.mention_repository import MentionRepository
from app.services.collection.cadence import (
    CadenceDecision,
    CadencePolicy,
    CadenceRates,
    PhaseCadencePolicy,
    VolumeEscalationRule,
    interval_for_rate,
)
from app.services.collection.cadence_cost import project_campaign_cost
from app.services.collection.mention_shape import NormalizedMention
from app.services.collection.source import (
    CollectedItem,
    CollectionPage,
    CollectionSource,
    CollectionWindow,
)
from app.services.collection.volume import MentionVolumeReader
from app.services.collection_schedule_service import CollectionScheduleService
from app.services.collection_service import CollectionService

# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------

ORGANIZATIONS_URL = "/api/v1/organizations"
SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures-cadence",
    "organization_type": "production_house",
}
DEFAULT_TITLE_PAYLOAD: dict[str, Any] = {
    "name": "Nova",
    "release_date": "2026-08-15",
    "aliases": [],
    "hashtags": [],
    "lead_cast": [],
    "directors": [],
    "music_directors": [],
    "exclusions": [],
}


def _titles_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/titles"


async def _create_organization(client: AsyncClient) -> str:
    response = await client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_title(client: AsyncClient, organization_id: str) -> str:
    response = await client.post(_titles_url(organization_id), json=DEFAULT_TITLE_PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _mention(
    *, title_id: uuid.UUID, external_id: str, posted_at: datetime, platform: Platform = Platform.X
) -> Mention:
    """A minimal, valid mention — only the fields the volume reader and the dedupe
    constraint care about are given meaningful values."""
    return Mention(
        title_id=title_id,
        platform=platform,
        external_id=external_id,
        author_handle="someuser",
        author_display_name="Some User",
        text="a post",
        posted_at=posted_at,
        collected_at=posted_at,
    )


async def _add_organization_and_title(
    session: AsyncSession, *, release_date: date, slug: str = "sun-pictures-cadence-unit"
) -> Title:
    organization = Organization(
        name="Sun Pictures", slug=slug, organization_type=OrganizationType.PRODUCTION_HOUSE
    )
    session.add(organization)
    await session.flush()
    title = Title(organization_id=organization.id, name="Nova", release_date=release_date)
    title.terms = []
    session.add(title)
    await session.flush()
    return title


def _freeze_collection_status_now(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    """Pins the instant `CollectionStatusService._current_cadence` reads as "now".

    `datetime.now(UTC)` is the only call site for `datetime` in that module, so replacing
    the name there is safe: nothing else in the module is affected, and the two reads this
    test takes are otherwise indistinguishable from two real requests made at different
    times, with no manual action taken in between — the exact shape the AC's "with no
    action required from me" describes.
    """

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return moment

    monkeypatch.setattr(collection_status_service_module, "datetime", _FrozenDatetime)


# ---------------------------------------------------------------------------
# Section 1 — The scenario. Exactly one test.
# ---------------------------------------------------------------------------


async def test_scenario_a_title_crosses_into_release_week_and_the_cadence_escalates_on_its_own(
    monkeypatch: pytest.MonkeyPatch, api_client: AsyncClient
) -> None:
    """Given: a title with a release date recorded, currently in the campaign phase at
    12 polls/day, under a policy defining dormant(2)/campaign(12)/surge(48) with the surge
    window derived from the release date, and a dashboard reading phase + rate live.

    When: the title enters its release-surge window.

    Then: polling steps up to the surge rate automatically and the dashboard shows the
    phase change — with no action taken between the two reads below beyond letting the
    clock move.
    """
    organization_id = await _create_organization(api_client)
    title_id = await _create_title(api_client, organization_id)

    # Given: currently in the campaign phase. release_date is 2026-08-15; 14 days out is
    # comfortably inside the campaign window (30 before to 28 after) and outside the surge
    # window (2 before to 4 after).
    campaign_moment = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    _freeze_collection_status_now(monkeypatch, campaign_moment)
    campaign_response = await api_client.get(f"/api/v1/titles/{title_id}/collection")
    assert campaign_response.status_code == 200
    campaign_body = campaign_response.json()
    assert campaign_body["cadence_phase"] == "campaign"
    assert campaign_body["polls_per_day"] == 12

    # When: the title enters its release-surge window. 1 day before release is inside
    # [release-2, release+4]. Nothing else happens between the two reads.
    surge_moment = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    _freeze_collection_status_now(monkeypatch, surge_moment)
    surge_response = await api_client.get(f"/api/v1/titles/{title_id}/collection")

    # Then: polling steps up to the surge rate automatically and the dashboard shows the
    # phase change.
    assert surge_response.status_code == 200
    surge_body = surge_response.json()
    assert surge_body["cadence_phase"] == "release_surge"
    assert surge_body["polls_per_day"] == 48
    # The calendar drove this, not a volume spike — the AC's own mechanism.
    assert surge_body["is_volume_escalated"] is False


# ---------------------------------------------------------------------------
# Section 2 — Directed: the concurrent double-poll retry, at surge cadence.
# ---------------------------------------------------------------------------


class _FixedPageSource(CollectionSource):
    """Returns one prebuilt page, however it is asked. Stands in for the network so the
    test controls exactly which items collide, rather than depending on an adapter."""

    def __init__(self, page: CollectionPage) -> None:
        self._page = page

    async def fetch(
        self,
        platform: Platform,
        query: str,
        *,
        page: str | None = None,
        limit: int,
        window: CollectionWindow | None = None,
    ) -> CollectionPage:
        return self._page


async def test_a_rival_insert_between_the_known_ids_read_and_the_commit_is_not_lost_or_duplicated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry `CollectionService._store_and_commit` performs when another writer stores
    part of the same page first — the exact overlap surge cadence (48/day) makes routine,
    per the story's Notes and the E03-S01 ledger entry naming this as unshipped-with-a-test.

    A genuine race, not a mocked exception: a second, independent session inserts one of
    the page's two mentions and commits it, timed to land between this writer's read of
    known external ids (inside `_store`) and its own commit, by patching
    `MentionRepository.add_all` — the call that sits at exactly that point in `_store` —
    to perform the rival insert on its first invocation only, before delegating to the
    real `add_all`. The unique constraint on `mentions` then rejects the writer's first
    attempt, `_store_and_commit` retries, and the retry's fresh read of known ids sees the
    rival's row and skips it.

    Uses a file-backed database and an independent reader session afterwards, per this
    task's own durability rule — the assertion is about what survived, not what one shared
    session merely believes happened.
    """
    db_path = tmp_path / "concurrent_double_poll.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    endpoint = get_endpoint("x.tikhub_search_timeline")
    assert endpoint is not None

    collided_external_id = "collide-1"
    safe_external_id = "safe-1"
    posted_at = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as setup_session:
            title = await _add_organization_and_title(
                setup_session, release_date=date(2026, 8, 15), slug="sun-pictures-double-poll"
            )
            await setup_session.commit()
            title_id = title.id

        page = CollectionPage(
            platform=Platform.X,
            endpoint=endpoint,
            adapter_version="test",
            items=[
                CollectedItem(
                    raw_payload={"id": collided_external_id},
                    external_id=collided_external_id,
                    mention=NormalizedMention(
                        platform=Platform.X,
                        external_id=collided_external_id,
                        text="the post another poll already stored",
                        posted_at=posted_at,
                        author_handle="rival_finder",
                        author_display_name="Rival Finder",
                    ),
                ),
                CollectedItem(
                    raw_payload={"id": safe_external_id},
                    external_id=safe_external_id,
                    mention=NormalizedMention(
                        platform=Platform.X,
                        external_id=safe_external_id,
                        text="a post only this poll found",
                        posted_at=posted_at,
                        author_handle="finder",
                        author_display_name="Finder",
                    ),
                ),
            ],
        )

        race_state = {"triggered": False}
        original_add_all = MentionRepository.add_all

        async def racing_add_all(self: MentionRepository, mentions: Any, payloads: Any) -> None:
            if not race_state["triggered"]:
                race_state["triggered"] = True
                async with session_factory() as rival_session:
                    rival_session.add(
                        _mention(
                            title_id=title_id,
                            external_id=collided_external_id,
                            posted_at=posted_at,
                        )
                    )
                    await rival_session.commit()
            await original_add_all(self, mentions, payloads)

        monkeypatch.setattr(MentionRepository, "add_all", racing_add_all)

        async with session_factory() as writer_session:
            service = CollectionService(writer_session, _FixedPageSource(page))
            result = await service.collect_page(title_id, Platform.X, "Nova", limit=20)

        async with session_factory() as reader_session:
            mentions = (
                (await reader_session.execute(select(Mention).where(Mention.title_id == title_id)))
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()

    # Nothing paid for is lost: the safe post landed even though the page's write
    # collided.
    assert result.stored == 1
    assert {m.external_id for m in mentions} == {collided_external_id, safe_external_id}
    # The collided post is not duplicated: exactly one row for it, however it got there.
    collided_rows = [m for m in mentions if m.external_id == collided_external_id]
    assert len(collided_rows) == 1


# ---------------------------------------------------------------------------
# Section 3 — Directed: an unplanned controversy in the dormant phase escalates cadence.
# ---------------------------------------------------------------------------


async def test_a_dormant_title_with_no_history_at_all_escalates_on_an_unplanned_volume_spike(
    db_session: AsyncSession,
) -> None:
    """The story's Notes, not the Gherkin: "Phase transitions must also be triggerable by
    observed volume, not only by calendar — an unplanned controversy in the dormant phase
    should escalate cadence."

    Built on the case `VolumeEscalationRule.is_spike`'s own docstring names: a title with
    no prior mentions at all has a baseline of zero, so any burst above the floor counts
    as unlike anything it has done before. Escalation is one step only
    (`CadencePhase.escalated`), so dormant (2/day) becomes campaign (12/day), never surge.
    """
    settings = Settings()
    rule = VolumeEscalationRule.from_settings(settings)
    # Release date ~205 days out: comfortably outside both the campaign window (30 days)
    # and the surge window (2 days), so the calendar alone says dormant.
    title = await _add_organization_and_title(
        db_session, release_date=date(2026, 10, 1), slug="sun-pictures-volume-escalation"
    )

    moment = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
    recent_start = moment - timedelta(hours=rule.recent_hours)
    for i in range(rule.minimum_mentions + 5):
        db_session.add(
            _mention(
                title_id=title.id,
                external_id=f"controversy-{i}",
                posted_at=recent_start + timedelta(minutes=i),
            )
        )
    await db_session.flush()

    policy = PhaseCadencePolicy(
        CadenceRates.from_settings(settings), MentionVolumeReader(db_session), rule
    )
    decision = await policy.decide(title, now=moment)

    assert decision.calendar_phase is CadencePhase.DORMANT
    assert decision.phase is CadencePhase.CAMPAIGN
    assert decision.polls_per_day == settings.collection_campaign_polls_per_day
    assert decision.is_volume_escalated is True


# ---------------------------------------------------------------------------
# Section 4 — phase_for_day's window boundaries are inclusive on both sides.
# ---------------------------------------------------------------------------


def test_phase_for_day_boundaries_are_inclusive_on_both_sides_of_every_window() -> None:
    """The calendar arithmetic every other part of this story reads from: the scheduler,
    the dashboard, and the ~$273 cost projection. Pins the exact boundary the task brief
    names ("a title exactly 2 days out is already surging; 31 days out is dormant") plus
    every other edge `phase_for_day` defines, since an off-by-one here never raises — it
    just silently polls at the wrong rate for exactly one day at each boundary.
    """
    release_date = date(2026, 8, 15)

    # Surge window: [release - 2, release + 4], inclusive both ends.
    assert (
        phase_for_day(release_date - timedelta(days=2), release_date) is CadencePhase.RELEASE_SURGE
    )
    assert phase_for_day(release_date - timedelta(days=3), release_date) is CadencePhase.CAMPAIGN
    assert (
        phase_for_day(release_date + timedelta(days=4), release_date) is CadencePhase.RELEASE_SURGE
    )
    assert phase_for_day(release_date + timedelta(days=5), release_date) is CadencePhase.CAMPAIGN
    assert phase_for_day(release_date, release_date) is CadencePhase.RELEASE_SURGE

    # Campaign window: [release - 30, release + 28], inclusive both ends.
    assert phase_for_day(release_date - timedelta(days=30), release_date) is CadencePhase.CAMPAIGN
    assert phase_for_day(release_date - timedelta(days=31), release_date) is CadencePhase.DORMANT
    assert phase_for_day(release_date + timedelta(days=28), release_date) is CadencePhase.CAMPAIGN
    assert phase_for_day(release_date + timedelta(days=29), release_date) is CadencePhase.DORMANT


# ---------------------------------------------------------------------------
# Section 5 — reconcile_pending_cadence is idempotent and one-directional.
# ---------------------------------------------------------------------------


class _ScriptedCadencePolicy(CadencePolicy):
    """Hands back one fixed decision, whatever title or moment it is asked about — the
    control this test needs to isolate `reconcile_pending_cadence`'s own arithmetic from
    the calendar and volume logic other tests already cover."""

    def __init__(self, decision: CadenceDecision) -> None:
        self._decision = decision

    async def decide(self, title: Title, *, now: datetime | None = None) -> CadenceDecision:
        return self._decision


async def test_reconcile_pending_cadence_is_idempotent_and_never_pushes_a_run_later(
    db_session: AsyncSession,
) -> None:
    """Two claims from the method's own docstring, neither in the Gherkin, both easy to
    get subtly wrong:

    "reconciling the same run on ten consecutive ticks gives the same answer as
    reconciling it once" — a queued cycle escalated once must not keep drifting earlier
    (or anywhere) on every later tick that reconsiders it at the same rate.

    "this can only ever make a title poll sooner... a de-escalation is left to take effect
    when the current cycle queues its successor" — a run whose stamped rate is already
    higher than what the policy would now decide must be left exactly alone, never pushed
    later.
    """
    escalating_title = await _add_organization_and_title(
        db_session, release_date=date(2026, 8, 15), slug="sun-pictures-reconcile-escalate"
    )
    stable_title = await _add_organization_and_title(
        db_session, release_date=date(2026, 8, 15), slug="sun-pictures-reconcile-stable"
    )

    now = datetime(2026, 3, 1, tzinfo=UTC)
    initial_scheduled_for = now + timedelta(hours=10)
    escalating_run = CollectionRun(
        title_id=escalating_title.id,
        status=CollectionRunStatus.QUEUED,
        trigger=CollectionRunTrigger.SCHEDULED,
        scheduled_for=initial_scheduled_for,
        polls_per_day=2,
        cadence_phase=CadencePhase.DORMANT,
        is_volume_escalated=False,
    )
    # A run whose stamped rate is already the surge rate — nothing a "poll harder" policy
    # says can move it, only a de-escalation, which must be ignored.
    stable_scheduled_for = now + timedelta(hours=1)
    stable_run = CollectionRun(
        title_id=stable_title.id,
        status=CollectionRunStatus.QUEUED,
        trigger=CollectionRunTrigger.SCHEDULED,
        scheduled_for=stable_scheduled_for,
        polls_per_day=48,
        cadence_phase=CadencePhase.RELEASE_SURGE,
        is_volume_escalated=False,
    )
    db_session.add_all([escalating_run, stable_run])
    await db_session.flush()

    escalating_decision = CadenceDecision(
        phase=CadencePhase.CAMPAIGN,
        calendar_phase=CadencePhase.CAMPAIGN,
        polls_per_day=12,
        is_volume_escalated=False,
    )
    de_escalating_decision = CadenceDecision(
        phase=CadencePhase.DORMANT,
        calendar_phase=CadencePhase.DORMANT,
        polls_per_day=2,
        is_volume_escalated=False,
    )

    escalating_schedule_service = CollectionScheduleService(
        db_session, _ScriptedCadencePolicy(escalating_decision)
    )
    stable_schedule_service = CollectionScheduleService(
        db_session, _ScriptedCadencePolicy(de_escalating_decision)
    )

    # One-directional: a policy that would now schedule this title less often than its
    # already-stamped rate must not touch it at all.
    stable_advanced = await stable_schedule_service.reconcile_pending_cadence(now=now, limit=10)
    assert stable_advanced == 0
    await db_session.refresh(stable_run)
    # SQLite hands the stored timestamp back naive; `as_utc` is the same normalisation
    # `app/core/timestamps.py` exists for.
    assert as_utc(stable_run.scheduled_for) == stable_scheduled_for
    assert stable_run.polls_per_day == 48

    # First reconciliation of the escalating run: it should be pulled forward, following
    # the same anchor arithmetic the docstring describes.
    first_advanced = await escalating_schedule_service.reconcile_pending_cadence(now=now, limit=10)
    assert first_advanced == 1
    await db_session.refresh(escalating_run)
    anchor = initial_scheduled_for - interval_for_rate(2)
    expected_scheduled_for = anchor + interval_for_rate(12)
    assert expected_scheduled_for < initial_scheduled_for
    assert as_utc(escalating_run.scheduled_for) == expected_scheduled_for
    assert escalating_run.polls_per_day == 12
    assert escalating_run.cadence_phase is CadencePhase.CAMPAIGN

    # Idempotent: reconciling the same run again, at the same rate the policy still
    # returns, must not move it a second time.
    for later_now in (now + timedelta(hours=1), now + timedelta(hours=2)):
        advanced_again = await escalating_schedule_service.reconcile_pending_cadence(
            now=later_now, limit=10
        )
        assert advanced_again == 0
        await db_session.refresh(escalating_run)
        assert as_utc(escalating_run.scheduled_for) == expected_scheduled_for


# ---------------------------------------------------------------------------
# Section 6 — MentionVolumeReader's baseline is the days a title actually has history for,
# not the configured window, when the two disagree.
# ---------------------------------------------------------------------------


async def test_a_titles_baseline_is_computed_over_days_it_actually_has_not_the_configured_window(
    db_session: AsyncSession,
) -> None:
    """A title that is only 3 days old must have its baseline mean divided by 3, not by
    the configured 14-day `baseline_days` window. Dividing by 14 when only 3 days of
    history exist understates the baseline five-fold, which turns a title's own ordinary,
    steady volume into what looks like a spike against its own diluted average — exactly
    the false "unplanned controversy" a brand-new title would trip on its first quiet
    week.

    Numbers are chosen so the two arithmetics disagree on the verdict, not just the
    number: at the true 3-day baseline this is completely ordinary volume (no spike); at a
    naive 14-day division it would incorrectly read as one.
    """
    settings = Settings()
    rule = VolumeEscalationRule.from_settings(settings)
    title = await _add_organization_and_title(
        db_session, release_date=date(2026, 10, 1), slug="sun-pictures-sparse-baseline"
    )

    moment = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
    recent_start = moment - timedelta(hours=rule.recent_hours)
    earliest_history = recent_start - timedelta(days=3)

    # 3 days of steady history at 25/day (75 total), all inside the true 3-day window and
    # nowhere near the configured 14-day one.
    for i in range(75):
        db_session.add(
            _mention(
                title_id=title.id,
                external_id=f"baseline-{i}",
                posted_at=earliest_history + timedelta(minutes=i),
            )
        )
    # The most recent 24h continues at the same steady rate — 25 posts, matching the
    # floor exactly and matching the true baseline exactly, i.e. not a spike at all.
    for i in range(25):
        db_session.add(
            _mention(
                title_id=title.id,
                external_id=f"recent-{i}",
                posted_at=recent_start + timedelta(minutes=i),
            )
        )
    await db_session.flush()

    reading = await MentionVolumeReader(db_session).read(title.id, now=moment, rule=rule)

    # 75 posts over the 3 days the title actually has history for, not over 14.
    assert reading.baseline_daily_mean == pytest.approx(25.0)
    assert reading.recent_count == 25
    # Steady volume against its own true baseline is not a spike. (Against a naive
    # 75/14 ≈ 5.36 baseline, the threshold would be ≈16.07 and 25 would incorrectly
    # clear it.)
    assert rule.is_spike(reading) is False


# ---------------------------------------------------------------------------
# Section 7 — Regression: a CAMPAIGN-phase volume spike is not allowed to buy surge rates.
# ---------------------------------------------------------------------------


async def test_a_campaign_phase_title_with_a_volume_spike_does_not_escalate_to_surge(
    db_session: AsyncSession,
) -> None:
    """The reviewer's finding on round 1: `_is_escalated_by_volume` only refused to
    escalate a title already *at* surge, not a CAMPAIGN-phase title. Combined with the
    generic one-step `CadencePhase.escalated`, a campaign title (12/day) with a volume
    spike escalated straight to RELEASE_SURGE (48/day) — a 4x jump on observed volume
    alone, with no calendar authority behind it. That contradicted this class's own
    docstring ("the worst a volume heuristic can do to a bill is move a title from 2/day to
    12/day. Surge rates stay the calendar's to grant.") and the story's Notes, which name
    only "an unplanned controversy in the dormant phase" as volume-escalatable — never
    campaign to surge.

    Same volume shape as the dormant escalation test above — no baseline history, so a
    burst past the floor (`minimum_mentions`) is a spike by construction — but with a
    release date placing "now" inside the calendar CAMPAIGN window instead of dormant, the
    way a trailer drop or song release routinely would. Run through
    `PhaseCadencePolicy.decide`, not `CadencePhase.is_volume_escalatable` in isolation:
    the bug was that the policy never consulted the ceiling, so a test of the predicate
    alone would still have passed with the bug present.
    """
    settings = Settings()
    rule = VolumeEscalationRule.from_settings(settings)
    moment = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
    # 15 days after "now": inside the campaign window (30 before to 28 after release) and
    # outside the surge window (2 before to 4 after), so the calendar alone says campaign.
    release_date = (moment + timedelta(days=15)).date()
    title = await _add_organization_and_title(
        db_session, release_date=release_date, slug="sun-pictures-campaign-volume-spike"
    )

    recent_start = moment - timedelta(hours=rule.recent_hours)
    for i in range(rule.minimum_mentions + 5):
        db_session.add(
            _mention(
                title_id=title.id,
                external_id=f"trailer-drop-{i}",
                posted_at=recent_start + timedelta(minutes=i),
            )
        )
    await db_session.flush()

    policy = PhaseCadencePolicy(
        CadenceRates.from_settings(settings), MentionVolumeReader(db_session), rule
    )
    decision = await policy.decide(title, now=moment)

    assert decision.calendar_phase is CadencePhase.CAMPAIGN
    # The regression: this must stay at campaign, never reach release_surge, however loud
    # the observed volume is.
    assert decision.phase is CadencePhase.CAMPAIGN
    assert decision.polls_per_day == settings.collection_campaign_polls_per_day
    assert decision.is_volume_escalated is False


# ---------------------------------------------------------------------------
# Section 8 — The ~$273/title cost projection, over the window cadence_phase.py derives it
# from.
# ---------------------------------------------------------------------------


def test_project_campaign_cost_over_the_docstrings_six_month_window_matches_the_notes_273_per_title() -> (  # noqa: E501
    None
):
    """The reviewer's second note: no test ever invoked `project_campaign_cost` and
    checked it against the concept note's own figure
    (concept-note-v0.2-social-intelligence-control-centre.md §7: "total collection lands
    around ~$273 per title"). That figure is what the campaign-phase escalation ceiling
    exercised above exists to protect, and the story's Notes name it as the thing any
    cadence-policy change must keep in sync.

    The window is not picked freehand: `app/core/cadence_phase.py`'s own module docstring
    states the derivation — a tracking window running 152 days before release to 30 days
    after (183 days, "the note's six-month campaign") — dormant 124 days, campaign 52,
    surge 7, for 1208 polls at $0.225 = $271.80, which rounds to the note's "~$273".

    This is the guard on the epic's cost gate, so the failure message is deliberately
    explicit: if this fails, a phase window or a rate moved, and the fix is to update
    concept-note-v0.2-social-intelligence-control-centre.md §7 (and any dependent figure in
    E09-S04) alongside it — not to edit this assertion to match whatever the code now
    produces.
    """
    settings = Settings()
    rates = CadenceRates.from_settings(settings)
    release_date = date(2026, 8, 15)
    tracked_from = release_date - timedelta(days=152)
    tracked_until = release_date + timedelta(days=30)

    projection = project_campaign_cost(
        release_date=release_date,
        tracked_from=tracked_from,
        tracked_until=tracked_until,
        rates=rates,
        cost_per_poll_usd=settings.collection_cost_per_poll_usd,
    )

    assert projection.total_days == 183
    assert projection.total_cost_usd == pytest.approx(271.80, abs=0.01), (
        f"A six-month campaign (152 days before release to 30 after) now projects to "
        f"${projection.total_cost_usd:.2f}, not the ~$273/title the concept note quotes "
        "in §7 and the epic's cost gate relies on. If a cadence rate or a phase-window "
        "boundary changed, update "
        "concept-note-v0.2-social-intelligence-control-centre.md §7 (and E09-S04's "
        "figures) together with this assertion — do not just move this number to match "
        "the new output."
    )

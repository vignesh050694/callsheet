"""Tests for E03-S01 — Get a populated dashboard within a day of creating a title, with
each post counted once no matter how many queries found it.

Story: stories/E03-agentic-collection-layer/E03-S01-collection-starts-and-counts-once.md
Epic: stories/E03-agentic-collection-layer/EPIC.md

The story has two Gherkin scenarios. Their Given/When/Then clauses, plus the notes and the
task brief's own coverage list, map to the sections below:

  - Scenario 1, "First collection run fires immediately after title setup completes" ->
    Section 1. "a first collection run is queued within one minute" is tested both as a
    unit (the schedule service alone) and durably, through the real HTTP path, with a
    file-backed database and independent per-request sessions — the two-session pattern
    `test_provider_agnostic_collection_interface.py`'s Section 12 established, adapted
    here because a title is created over several separate requests rather than one
    in-process call. "the title has no prior collection history" / dashboard shows
    "Collecting your first mentions" -> `CollectionStatusService`'s
    `is_awaiting_first_results`. "queued... share a transaction" (from the story's own
    architecture, restated in `title_service.py`'s docstring) -> the atomicity test, same
    durable pattern, with a schedule service double that always fails. "shows real
    mentions in under 24 hours without any manual intervention" -> the end-to-end test
    that runs the worker tick (`run_due_cycles`) once and reads the dashboard back.

  - Scenario 2, "The same post is returned by several query variants in one polling
    cycle" -> Section 2, the most important tests in this file. "runs five query variants
    per platform per poll" / "a single popular post matches three of those variants" is
    built exactly as stated: a title generating precisely five variants (Section 0's
    `five_variant_title_id` fixture), with the popular post placed on exactly three of
    them by a transport that returns a distinct, scripted page per call
    (`SequencedTikhubTransport`) rather than depending on the literal query text
    `query_plan` builds — that text is what Section 6 already tests in isolation.
    "contributes exactly one mention to volume, sentiment, and every chart" -> the mention
    count and corpus size assertions. "the matched-variant list is retained" -> the
    `MentionQueryMatch` assertions.

Additional coverage from the task brief, each in its own section:

  - Section 3 — attribution covers a post stored in an *earlier* cycle when a *later*
    cycle's new variant finds it, not only posts stored in the same cycle that found them.
  - Section 4 — re-polling an identical page on a later cycle is a true no-op: no new
    mentions, no duplicate attribution rows.
  - Section 5 — exclusion terms never become a query (also asserted structurally in the
    story's own notes).
  - Section 6 — the query plan is deterministic, and the cap drops the weakest variants
    rather than reshuffling the ones already included.
  - Section 7 — a cycle always queues its successor: after success, after a spend
    refusal, and after a crash. A title must never be left with nothing owed to it.
  - Section 8 — a crashed run is not left stuck in `running`.
  - Section 9 — a spend policy that refuses causes zero provider calls.
  - Section 10 — a platform whose route cannot resolve is tried once per cycle, not once
    per variant, and a cycle where nothing could be collected is `skipped`, never
    `succeeded`.
  - Section 11 — only one pending run per title: `queue_next_run` and `queue_manual_run`
    both decline while one is already owed, and both work again once it has finished.
  - Section 12 — `GET /titles/{id}/collection`: access control (a non-member gets 404,
    not 403, the same posture `TitleService` and `CollectionStatusService` take
    everywhere else) and the `is_awaiting_first_results`/`is_stalled` states.
  - Section 13 — the reprocess corpus walk (E03-S04, unchanged in behaviour here but
    reading a cursor this story's scheduler makes reachable for the first time) survives
    a mention inserted by a concurrent process mid-walk, which is exactly the failure mode
    `MentionRepository.list_for_title_in_window`'s docstring says the `(collected_at, id)`
    cursor exists to fix. The rest of E03-S04's suite is re-run as part of this task and
    reported on separately rather than duplicated here.

No test calls Monid. `SequencedTikhubTransport` below plays the same role
`FixtureTransport` plays in the E03-S07 and E03-S04 suites, except it is scripted by call
order rather than by a fixed capture, because this story is about the fan-out and dedupe
*mechanics* across several variants and cycles, not about one provider's payload shape —
that fidelity is already covered by the committed captures those suites replay. Every
synthetic item built here is shaped exactly like a real tikhub item
(`x_tikhub_search_timeline.json`) so it exercises the real `TikhubXSearchAdapter`, the same
principle the E03-S04 suite uses for its own synthetic mentions.
"""

import importlib
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import structlog
import structlog.testing
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession

import app.services.collection.spend_policy as spend_policy_module
import app.services.reprocess_service as reprocess_service_module
from app.core.cadence_phase import CadencePhase
from app.core.collection_endpoints import get_endpoint
from app.core.config import MAX_POLLS_PER_DAY, MIN_POLLS_PER_DAY, Settings
from app.core.exceptions import ServiceUnavailableError
from app.core.identity_terms import normalize_term
from app.core.platforms import Platform
from app.core.timestamps import as_utc
from app.db.session import get_db_session
from app.main import create_app
from app.models import Base
from app.models.collection_run import CollectionRun, CollectionRunStatus, CollectionRunTrigger
from app.models.membership import Membership, MembershipRole
from app.models.mention import Mention, MentionRawPayload
from app.models.mention_query_match import MentionQueryMatch
from app.models.organization import Organization, OrganizationType
from app.models.title import Title, TitleTerm, TitleTermType
from app.models.user import User
from app.repositories.collection_run_repository import CollectionRunRepository
from app.repositories.mention_query_match_repository import MentionQueryMatchRepository
from app.repositories.mention_repository import MentionRepository
from app.repositories.title_repository import TitleRepository
from app.schemas.title import TitleCreate
from app.services.analysis.mention_analyzer import (
    AnalysisVerdict,
    AnalyzableMention,
    MentionAnalyzer,
)
from app.services.collection.adapters.base import ProviderRequest
from app.services.collection.cadence import (
    CadenceDecision,
    CadencePolicy,
    FixedCadencePolicy,
)
from app.services.collection.mention_shape import MentionEngagement, NormalizedMention
from app.services.collection.monid_source import MonidCollectionSource, MonidTransport
from app.services.collection.query_plan import (
    _query_for_term,
    _QueryStyle,
    build_query_variants,
    ordered_identity_terms,
)
from app.services.collection.source import CollectedItem, CollectionPage, CollectionSource
from app.services.collection.spend_policy import SpendDecision, SpendPolicy, UnrestrictedSpendPolicy
from app.services.collection_run_service import (
    ABANDONED_REASON,
    CollectionCycleResult,
    CollectionRunService,
)
from app.services.collection_schedule_service import CollectionScheduleService
from app.services.collection_service import CollectionService
from app.services.collection_status_service import CollectionStatusService
from app.services.reprocess_service import ReprocessService
from app.services.title_service import TitleService

# ---------------------------------------------------------------------------
# Section 0 — Fixtures and helpers.
# ---------------------------------------------------------------------------

ORGANIZATIONS_URL = "/api/v1/organizations"
SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
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


def _title_payload(**overrides: Any) -> dict[str, Any]:
    return {**DEFAULT_TITLE_PAYLOAD, **overrides}


async def _create_organization(client: AsyncClient) -> str:
    response = await client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_title(client: AsyncClient, organization_id: str, payload: dict[str, Any]) -> str:
    response = await client.post(_titles_url(organization_id), json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
async def title_id(api_client: AsyncClient) -> uuid.UUID:
    """A plain title: name only, one variant, no fan-out — used by tests that only care
    about scheduling and cycle mechanics, not about several variants at once."""
    organization_id = await _create_organization(api_client)
    raw_id = await _create_title(api_client, organization_id, _title_payload())
    return uuid.UUID(raw_id)


# The identity set built so `build_query_variants` produces exactly the five variants the
# story's second scenario names: "name", "hashtag:nova", "alias:star fall",
# "director:sam ito", "music_director:cy fox" — verified directly against the real
# function, not asserted from a guess at its behaviour (see Section 6).
FIVE_VARIANT_KEYS = (
    "name",
    "hashtag:nova",
    "alias:star fall",
    "director:sam ito",
    "music_director:cy fox",
)


@pytest.fixture
async def five_variant_title_id(api_client: AsyncClient) -> uuid.UUID:
    organization_id = await _create_organization(api_client)
    raw_id = await _create_title(
        api_client,
        organization_id,
        _title_payload(
            aliases=["Star Fall"],
            hashtags=["#Nova"],
            lead_cast=["Rea Lin"],
            directors=["Sam Ito"],
            music_directors=["Cy Fox"],
        ),
    )
    return uuid.UUID(raw_id)


def _build_title(
    *,
    name: str = "Nova",
    hashtags: list[str] | None = None,
    aliases: list[str] | None = None,
    cast: list[str] | None = None,
    directors: list[str] | None = None,
    music_directors: list[str] | None = None,
    exclusions: list[str] | None = None,
) -> Title:
    """An in-memory title with a loaded `terms` list, for exercising `build_query_variants`
    without a database. `title.terms` is `lazy="raise"` precisely so the function only
    reads what is already loaded — an in-memory list satisfies that the same as a
    `selectinload`-ed one would. Terms are built in the same field order
    `TitleService._build_identity_terms` uses (alias, hashtag, cast, director,
    music_director, exclusion), because that order is what decides which anchor leads."""
    title = Title(name=name, release_date=date(2026, 8, 15))
    title.id = uuid.uuid4()
    term_specs: list[tuple[TitleTermType, list[str]]] = [
        (TitleTermType.ALIAS, aliases or []),
        (TitleTermType.HASHTAG, hashtags or []),
        (TitleTermType.CAST, cast or []),
        (TitleTermType.DIRECTOR, directors or []),
        (TitleTermType.MUSIC_DIRECTOR, music_directors or []),
        (TitleTermType.EXCLUSION, exclusions or []),
    ]
    title.terms = [
        TitleTerm(term_type=term_type, value=value, normalized_value=normalize_term(value))
        for term_type, values in term_specs
        for value in values
    ]
    return title


def _tweet_item(tweet_id: str, *, text: str = "a post") -> dict[str, Any]:
    """A synthetic tikhub timeline item, real enough for `TikhubXSearchAdapter.to_mention`
    to succeed — see this module's docstring for why synthetic items are used here rather
    than the committed capture."""
    return {
        "type": "tweet",
        "tweet_id": tweet_id,
        "screen_name": "someuser",
        "text": text,
        "created_at": "Tue Aug 11 17:41:52 +0000 2026",
    }


def _tikhub_response(*tweet_ids: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "timeline": [_tweet_item(tweet_id) for tweet_id in tweet_ids],
        "next_cursor": None,
    }


class SequencedTikhubTransport(MonidTransport):
    """Returns one scripted response per call, in the order calls arrive, cycling back to
    the start if asked for more calls than it was given — which is what lets one instance
    serve a second cycle's identical re-poll (Section 4). Spends nothing; a real Monid call
    never happens.

    Deliberately scripted by call order rather than by the query text, unlike
    `FixtureTransport` in the E03-S07/E03-S04 suites: this story's tests are about the
    fan-out and dedupe mechanics across several variants, and pinning exact query strings
    here would duplicate what Section 6 already tests directly against `query_plan`.
    """

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, ProviderRequest]] = []

    async def run(self, endpoint: Any, request: ProviderRequest) -> Any:
        index = len(self.calls) % len(self._responses)
        self.calls.append((endpoint.key, request))
        return self._responses[index]


def _build_run_service(
    session: AsyncSession,
    transport: MonidTransport,
    *,
    settings: Settings | None = None,
    spend_policy: SpendPolicy | None = None,
    cadence: CadencePolicy | None = None,
) -> CollectionRunService:
    settings = settings or Settings()
    source = MonidCollectionSource(transport, settings)
    return _build_run_service_with_source(
        session, source, settings=settings, spend_policy=spend_policy, cadence=cadence
    )


def _build_run_service_with_source(
    session: AsyncSession,
    source: CollectionSource,
    *,
    settings: Settings | None = None,
    spend_policy: SpendPolicy | None = None,
    cadence: CadencePolicy | None = None,
) -> CollectionRunService:
    settings = settings or Settings()
    collection_service = CollectionService(session, source)
    schedule_service = CollectionScheduleService(
        session, cadence or FixedCadencePolicy(settings.collection_polls_per_day)
    )
    return CollectionRunService(
        session,
        collection_service,
        schedule_service,
        spend_policy or UnrestrictedSpendPolicy(),
        settings,
    )


async def _pending_run(session: AsyncSession, title_id: uuid.UUID) -> CollectionRun:
    run = await CollectionRunRepository(session).next_pending_for_title(title_id)
    assert run is not None, "expected a pending collection run for this title"
    return run


class _CountingRefusingSource(CollectionSource):
    """A `CollectionSource` double standing in for a platform whose route cannot resolve
    (no endpoint configured, no adapter for the one that is) — the exact refusal
    `resolve_route` raises in the E03-S07 suite, reused here as a seam rather than
    re-exercising routing internals this story does not own."""

    def __init__(self, message: str = "no adapter for this endpoint") -> None:
        self.calls = 0
        self._message = message

    async def fetch(
        self, platform: Platform, query: str, *, page: str | None = None, limit: int
    ) -> Any:
        self.calls += 1
        raise ServiceUnavailableError(self._message)


class _CrashingSource(CollectionSource):
    """A `CollectionSource` double standing in for an unexpected failure mid-poll — a
    dropped connection, a provider returning nonsense — as opposed to the clean,
    typed refusal `_CountingRefusingSource` models."""

    async def fetch(
        self, platform: Platform, query: str, *, page: str | None = None, limit: int
    ) -> Any:
        raise RuntimeError("provider connection dropped mid-poll")


class _RefusingSpendPolicy(SpendPolicy):
    def __init__(self, reason: str = "budget exhausted for this organization") -> None:
        self._reason = reason

    async def decide(self, organization_id: uuid.UUID) -> SpendDecision:
        return SpendDecision(is_allowed=False, reason=self._reason)


# ---------------------------------------------------------------------------
# Section 1 — Scenario 1: a first collection run fires immediately after title setup.
# ---------------------------------------------------------------------------


async def test_queue_first_run_schedules_it_due_immediately_with_trigger_title_created(
    db_session: AsyncSession,
) -> None:
    """Unit-level: `CollectionScheduleService.queue_first_run` on its own, independent of
    the HTTP path Section 1's durability tests exercise below."""
    organization = Organization(
        name="Sun Pictures",
        slug="sun-pictures-unit",
        organization_type=OrganizationType.PRODUCTION_HOUSE,
    )
    db_session.add(organization)
    await db_session.flush()
    title = Title(organization_id=organization.id, name="Nova", release_date=date(2026, 8, 15))
    title.terms = []
    db_session.add(title)
    await db_session.flush()

    before = datetime.now(UTC)
    schedule_service = CollectionScheduleService(db_session, FixedCadencePolicy(12))
    run = await schedule_service.queue_first_run(title)
    after = datetime.now(UTC)

    assert run.trigger is CollectionRunTrigger.TITLE_CREATED
    assert run.status is CollectionRunStatus.QUEUED
    assert run.polls_per_day == 12
    # "queued within one minute" (AC) — here, due immediately, well inside that bound.
    assert before <= run.scheduled_for <= after + timedelta(minutes=1)


async def test_creating_a_title_through_the_api_durably_queues_exactly_one_run_within_a_minute(
    tmp_path: Path,
) -> None:
    """The AC's own words: "a first collection run is queued within one minute" of
    completing title setup, and it must survive the request that created it — not merely
    be visible to the same session that wrote it.

    Uses a file-backed database with a fresh session per HTTP request (mirroring
    `get_db_session` in production, not the shared single-session test override
    `conftest.py` uses elsewhere), plus one further independent reader session opened only
    after every request has completed and its client closed. This is the two-session
    durability pattern `test_provider_agnostic_collection_interface.py` Section 12
    establishes, adapted for a resource built across several HTTP requests rather than one
    in-process service call.
    """
    db_path = tmp_path / "title_creation_durability.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    before = datetime.now(UTC)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as setup_session:
            user = User(email="owner@sunpictures.com", display_name="Owner", is_email_verified=True)
            setup_session.add(user)
            await setup_session.commit()
            user_id = user.id

        app = create_app()

        async def override_get_db_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_db_session] = override_get_db_session
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.headers["X-User-Id"] = str(user_id)
            organization_id = await _create_organization(client)
            title_id = uuid.UUID(await _create_title(client, organization_id, _title_payload()))
        app.dependency_overrides.clear()
        after = datetime.now(UTC)

        async with session_factory() as reader_session:
            runs = (
                (
                    await reader_session.execute(
                        select(CollectionRun).where(CollectionRun.title_id == title_id)
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()

    assert len(runs) == 1
    run = runs[0]
    assert run.trigger is CollectionRunTrigger.TITLE_CREATED
    assert run.status is CollectionRunStatus.QUEUED
    # SQLite hands the stored timestamp back naive; `as_utc` is the same normalisation
    # `app/core/timestamps.py` exists for, reused here rather than reimplemented.
    scheduled_for = as_utc(run.scheduled_for)
    assert before <= scheduled_for <= after + timedelta(minutes=1)


async def test_if_queuing_the_first_run_fails_the_title_is_not_created_either(
    tmp_path: Path,
) -> None:
    """`TitleService.create_title` catches only `IntegrityError`, so a failure inside the
    scheduler propagates out of the whole call and nothing is committed — the atomicity
    the story's architecture depends on ("either both rows land or neither does",
    `collection_schedule_service.py`).

    A schedule-service double that always raises is wired into a real `TitleService` over
    a file-backed database. The writer session is closed without a commit or rollback,
    exactly as an unhandled exception in a real request would leave it — the same
    durability pattern Section 1's other tests use, verifying the *absence* of a write
    rather than its presence.
    """
    db_path = tmp_path / "title_creation_atomicity.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    class _AlwaysRefusingScheduleService:
        async def queue_first_run(
            self, title: Title, *, now: datetime | None = None
        ) -> CollectionRun:
            raise RuntimeError("simulated scheduler failure")

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as writer_session:
            organization = Organization(
                name="Sun Pictures",
                slug="sun-pictures-atomic",
                organization_type=OrganizationType.PRODUCTION_HOUSE,
            )
            user = User(email="owner@sunpictures.com", display_name="Owner", is_email_verified=True)
            writer_session.add_all([organization, user])
            await writer_session.flush()
            membership = Membership(
                user_id=user.id, organization_id=organization.id, role=MembershipRole.OWNER
            )
            writer_session.add(membership)
            await writer_session.commit()
            organization_id = organization.id

            broken_schedule_service = _AlwaysRefusingScheduleService()
            # type: ignore[arg-type] — the double duck-types the one method used.
            title_service = TitleService(writer_session, broken_schedule_service)  # type: ignore
            payload = TitleCreate(name="Nova", release_date=date(2026, 8, 15))

            with pytest.raises(RuntimeError, match="simulated scheduler failure"):
                await title_service.create_title(organization_id, payload, user)
            # Deliberately no rollback/commit here — see the docstring above.

        async with session_factory() as reader_session:
            titles = (await reader_session.execute(select(Title))).scalars().all()
            runs = (await reader_session.execute(select(CollectionRun))).scalars().all()
    finally:
        await engine.dispose()

    assert titles == []
    assert runs == []


async def test_collection_status_shows_awaiting_first_results_before_any_mention_lands(
    api_client: AsyncClient, title_id: uuid.UUID
) -> None:
    """The AC: "the dashboard shows a 'Collecting your first mentions' state until data
    lands" — the read `TitleCollectionStatusRead.is_awaiting_first_results` backs."""
    response = await api_client.get(f"/api/v1/titles/{title_id}/collection")

    assert response.status_code == 200
    body = response.json()
    assert body["is_awaiting_first_results"] is True
    assert body["is_stalled"] is False
    assert body["unsegmented_mention_count"] == 0
    assert body["next_run_at"] is not None


async def test_running_the_queued_first_run_produces_real_mentions_with_no_manual_intervention(
    db_session: AsyncSession, api_client: AsyncClient, five_variant_title_id: uuid.UUID
) -> None:
    """The AC's Then clause, end to end: the title's own auto-queued first run, claimed
    and executed the way the worker (`scripts/run_collection.py`) does via
    `run_due_cycles`, with the dashboard read back afterwards — no manual poll triggered
    anywhere in this test."""
    responses = [
        _tikhub_response("alpha-1"),
        _tikhub_response("beta-1"),
        _tikhub_response("gamma-1"),
        _tikhub_response("delta-1"),
        _tikhub_response("epsilon-1"),
    ]
    transport = SequencedTikhubTransport(responses)
    service = _build_run_service(db_session, transport)

    results = await service.run_due_cycles()

    assert len(results) == 1
    assert results[0].status is CollectionRunStatus.SUCCEEDED
    assert results[0].mentions_stored == 5

    response = await api_client.get(f"/api/v1/titles/{five_variant_title_id}/collection")
    assert response.status_code == 200
    body = response.json()
    assert body["unsegmented_mention_count"] == 5
    assert body["is_awaiting_first_results"] is False
    assert body["is_stalled"] is False
    assert body["last_run_status"] == "succeeded"


# ---------------------------------------------------------------------------
# Section 2 — Scenario 2: the same post returned by several query variants in one cycle
# contributes exactly one mention, with every matching variant retained.
# ---------------------------------------------------------------------------

POP_TWEET_ID = "pop-1"
OTHER_TWEET_IDS: dict[str, str] = {
    "name": "other-name-1",
    "hashtag:nova": "other-hashtag-1",
    "alias:star fall": "other-alias-1",
    "director:sam ito": "other-director-1",
    "music_director:cy fox": "other-music-director-1",
}
# The popular post matches three of the title's five variants — the exact shape the
# scenario names ("a single popular post matches three of those variants").
POP_MATCHING_VARIANTS = ("name", "alias:star fall", "music_director:cy fox")


def _five_variant_cycle_responses() -> list[dict[str, Any]]:
    responses = []
    for variant_key in FIVE_VARIANT_KEYS:
        tweet_ids = [OTHER_TWEET_IDS[variant_key]]
        if variant_key in POP_MATCHING_VARIANTS:
            tweet_ids.append(POP_TWEET_ID)
        responses.append(_tikhub_response(*tweet_ids))
    return responses


@dataclass
class _FiveVariantCycle:
    title_id: uuid.UUID
    result: CollectionCycleResult
    pop_mention_id: uuid.UUID
    other_mention_ids: dict[str, uuid.UUID]


@pytest.fixture
async def five_variant_cycle(
    db_session: AsyncSession, five_variant_title_id: uuid.UUID
) -> _FiveVariantCycle:
    """Runs the title's real, auto-queued first cycle across exactly five variants, with
    the popular post on three of them and a distinct post on each of the other two — the
    scenario's own worked example, built from a title whose variant keys are verified in
    Section 6 rather than assumed here."""
    transport = SequencedTikhubTransport(_five_variant_cycle_responses())
    service = _build_run_service(db_session, transport)
    run = await _pending_run(db_session, five_variant_title_id)

    result = await service.execute_run(run)

    mention_repository = MentionRepository(db_session)
    all_ids = [POP_TWEET_ID, *OTHER_TWEET_IDS.values()]
    id_by_external_id = await mention_repository.ids_by_external_id(
        five_variant_title_id, Platform.X, all_ids
    )
    other_mention_ids = {
        variant_key: id_by_external_id[tweet_id]
        for variant_key, tweet_id in OTHER_TWEET_IDS.items()
    }
    return _FiveVariantCycle(
        title_id=five_variant_title_id,
        result=result,
        pop_mention_id=id_by_external_id[POP_TWEET_ID],
        other_mention_ids=other_mention_ids,
    )


async def test_five_variants_actually_ran_against_the_five_variant_title(
    five_variant_cycle: _FiveVariantCycle,
) -> None:
    """Confirms the fixture's own premise before trusting the assertions built on it: the
    cycle really did plan and run five variants, matching "my title runs five query
    variants per platform per poll" (Given)."""
    assert five_variant_cycle.result.variants_planned == 5
    assert five_variant_cycle.result.status is CollectionRunStatus.SUCCEEDED


async def test_a_post_matching_three_of_five_variants_contributes_exactly_one_mention(
    db_session: AsyncSession, five_variant_cycle: _FiveVariantCycle
) -> None:
    mentions = await MentionRepository(db_session).list_for_title(
        five_variant_cycle.title_id, limit=100
    )
    matching_pop_tweet = [m for m in mentions if m.external_id == POP_TWEET_ID]
    assert len(matching_pop_tweet) == 1


async def test_a_post_matching_three_of_five_variants_is_not_over_counted_in_the_mention_total(
    db_session: AsyncSession, five_variant_cycle: _FiveVariantCycle
) -> None:
    """The Then clause: "contributes exactly one mention to volume, sentiment, and every
    chart" — the corpus-wide count, which is what every chart actually reads, is 6: the
    popular post once, plus the five distinct "other" posts, one per variant slot."""
    count = await MentionRepository(db_session).count_for_title(five_variant_cycle.title_id)
    assert count == 6


async def test_a_post_matching_three_of_five_variants_has_all_three_matching_variants_recorded(
    db_session: AsyncSession, five_variant_cycle: _FiveVariantCycle
) -> None:
    """The Then clause: "the matched-variant list is retained for alias-discovery
    analysis" — every variant that found the post, and no others."""
    matched_variants = await MentionQueryMatchRepository(db_session).variants_for_mention(
        five_variant_cycle.pop_mention_id
    )
    assert set(matched_variants) == set(POP_MATCHING_VARIANTS)
    assert len(matched_variants) == 3


async def test_a_post_found_by_only_one_variant_is_attributed_to_that_variant_alone(
    db_session: AsyncSession, five_variant_cycle: _FiveVariantCycle
) -> None:
    match_repository = MentionQueryMatchRepository(db_session)
    for variant_key, mention_id in five_variant_cycle.other_mention_ids.items():
        matched = await match_repository.variants_for_mention(mention_id)
        assert matched == [variant_key], variant_key


async def test_the_cycle_reports_stored_mentions_net_of_the_shared_posts_duplicate_finds(
    five_variant_cycle: _FiveVariantCycle,
) -> None:
    """The run's own counters must agree with the corpus: 6 stored (the popular post
    once, on the first variant slot that found it, plus 5 distinct others), and the
    remaining 2 sightings of the popular post reported as already known rather than
    stored again."""
    assert five_variant_cycle.result.mentions_stored == 6
    assert five_variant_cycle.result.mentions_already_known == 2


async def test_the_shared_posts_one_mention_and_three_matches_survive_in_an_independent_session(
    tmp_path: Path,
) -> None:
    """Regression (review round 3): `CollectionRunService._attribute` and `_finish` both
    had their `await self._session.commit()` deleted by the reviewer, and the 40 tests in
    this file all still passed — because every test above this one rides the shared
    `conftest` `db_session` fixture, which hands every call in a test the SAME open,
    uncommitted session, so a read-after-write always succeeds whether or not anything was
    ever committed. This is the identical defect class the epic ledger records biting
    E03-S07's first review round ("No test built on those fixtures could ever have caught
    it"). This test uses its own file-backed database and a session independent of the one
    that ran the cycle, exactly as `test_collect_page_commits_so_a_second_independent_...`
    does in `test_provider_agnostic_collection_interface.py`, so it can actually tell a
    commit from a flush.

    Sensitivity was verified by hand: temporarily deleting both commits and rerunning this
    test alone makes it fail — the reader session sees zero `mention_query_matches` rows
    for the popular post instead of three, because closing `writer_session` without a
    commit rolls back everything `_attribute` added and everything `_finish` closed.
    Restoring the two lines makes it pass again. See the task report for the exact
    command and output.
    """
    db_path = tmp_path / "attribution_durability.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as writer_session:
            organization = Organization(
                name="Sun Pictures",
                slug="sun-pictures-attribution-durability",
                organization_type=OrganizationType.PRODUCTION_HOUSE,
            )
            writer_session.add(organization)
            await writer_session.flush()
            title = Title(
                organization_id=organization.id, name="Nova", release_date=date(2026, 8, 15)
            )
            title.terms = [
                TitleTerm(
                    term_type=TitleTermType.ALIAS,
                    value="Star Fall",
                    normalized_value=normalize_term("Star Fall"),
                ),
                TitleTerm(
                    term_type=TitleTermType.HASHTAG,
                    value="#Nova",
                    normalized_value=normalize_term("#Nova"),
                ),
                TitleTerm(
                    term_type=TitleTermType.CAST,
                    value="Rea Lin",
                    normalized_value=normalize_term("Rea Lin"),
                ),
                TitleTerm(
                    term_type=TitleTermType.DIRECTOR,
                    value="Sam Ito",
                    normalized_value=normalize_term("Sam Ito"),
                ),
                TitleTerm(
                    term_type=TitleTermType.MUSIC_DIRECTOR,
                    value="Cy Fox",
                    normalized_value=normalize_term("Cy Fox"),
                ),
            ]
            writer_session.add(title)
            await writer_session.flush()
            title_id = title.id

            cadence = FixedCadencePolicy(12)
            schedule_service = CollectionScheduleService(writer_session, cadence)
            await schedule_service.queue_first_run(title)
            await writer_session.commit()

            transport = SequencedTikhubTransport(_five_variant_cycle_responses())
            settings = Settings()
            source = MonidCollectionSource(transport, settings)
            collection_service = CollectionService(writer_session, source)
            run_service = CollectionRunService(
                writer_session,
                collection_service,
                schedule_service,
                UnrestrictedSpendPolicy(),
                settings,
            )
            run = await _pending_run(writer_session, title_id)
            await run_service.execute_run(run)
            # Deliberately no commit here beyond whatever `execute_run` performed itself —
            # the whole point is to observe only what the service actually committed.

        async with session_factory() as reader_session:
            mentions = (
                (await reader_session.execute(select(Mention).where(Mention.title_id == title_id)))
                .scalars()
                .all()
            )
            pop_mention = next(m for m in mentions if m.external_id == POP_TWEET_ID)
            matches = (
                (
                    await reader_session.execute(
                        select(MentionQueryMatch).where(
                            MentionQueryMatch.mention_id == pop_mention.id
                        )
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()

    assert len(mentions) == 6
    assert len(matches) == 3
    assert {match.query_variant for match in matches} == set(POP_MATCHING_VARIANTS)


# ---------------------------------------------------------------------------
# Section 3 — Attribution covers posts stored in an earlier cycle too, not only ones
# stored in the same cycle that found them.
# ---------------------------------------------------------------------------


async def test_a_post_stored_in_an_earlier_cycle_gains_attribution_from_a_new_variant_later(
    db_session: AsyncSession, five_variant_title_id: uuid.UUID
) -> None:
    # Cycle 1: only "name" finds the popular post.
    cycle_one = [
        _tikhub_response(POP_TWEET_ID) if key == "name" else _tikhub_response()
        for key in FIVE_VARIANT_KEYS
    ]
    # Cycle 2: "name" no longer returns it (its own poll moved on), but "hashtag:nova"
    # now finds the very same, already-stored post — isolating "a new variant finds an
    # old post" from "the same variant re-finds it".
    cycle_two = [
        _tikhub_response(POP_TWEET_ID) if key == "hashtag:nova" else _tikhub_response()
        for key in FIVE_VARIANT_KEYS
    ]
    transport = SequencedTikhubTransport(cycle_one + cycle_two)
    service = _build_run_service(db_session, transport)

    first_result = await service.execute_run(await _pending_run(db_session, five_variant_title_id))
    second_result = await service.execute_run(await _pending_run(db_session, five_variant_title_id))

    assert first_result.mentions_stored == 1
    assert second_result.mentions_stored == 0
    assert second_result.mentions_already_known == 1

    mention_repository = MentionRepository(db_session)
    id_by_external_id = await mention_repository.ids_by_external_id(
        five_variant_title_id, Platform.X, [POP_TWEET_ID]
    )
    pop_mention_id = id_by_external_id[POP_TWEET_ID]
    matched_variants = await MentionQueryMatchRepository(db_session).variants_for_mention(
        pop_mention_id
    )

    assert set(matched_variants) == {"name", "hashtag:nova"}
    assert await mention_repository.count_for_title(five_variant_title_id) == 1


# ---------------------------------------------------------------------------
# Section 4 — Re-polling the identical page on a later cycle adds no mentions and no
# duplicate attribution rows.
# ---------------------------------------------------------------------------


async def test_repolling_the_identical_page_on_a_later_cycle_adds_no_mentions_or_matches(
    db_session: AsyncSession, five_variant_title_id: uuid.UUID
) -> None:
    responses = _five_variant_cycle_responses()
    # `SequencedTikhubTransport` cycles back to `responses[0]` once exhausted, so the
    # second cycle below sees byte-for-byte the same five pages as the first.
    transport = SequencedTikhubTransport(responses)
    service = _build_run_service(db_session, transport)
    match_repository = MentionQueryMatchRepository(db_session)
    mention_repository = MentionRepository(db_session)

    first_result = await service.execute_run(await _pending_run(db_session, five_variant_title_id))
    matches_after_first_cycle = await match_repository.count_for_title(five_variant_title_id)

    second_result = await service.execute_run(await _pending_run(db_session, five_variant_title_id))
    matches_after_second_cycle = await match_repository.count_for_title(five_variant_title_id)

    assert first_result.mentions_stored == 6
    assert second_result.mentions_stored == 0
    # 8, not 6: the popular post is returned by three of the five variant pages in every
    # cycle, so a full identical re-poll sees 8 total sightings (5 distinct others + the
    # popular post 3 times over), every one of them already known the second time round.
    assert second_result.mentions_already_known == 8
    assert matches_after_second_cycle == matches_after_first_cycle
    assert await mention_repository.count_for_title(five_variant_title_id) == 6


# ---------------------------------------------------------------------------
# Section 5 — Exclusion terms never become a query.
# ---------------------------------------------------------------------------


def test_exclusion_terms_never_appear_as_a_query_variants_key_query_or_source_term() -> None:
    title = _build_title(
        name="Nova",
        hashtags=["#Nova"],
        directors=["Sam Ito"],
        exclusions=["Bad Studio Nova"],
    )

    variants = build_query_variants(title, limit=10)

    assert variants  # the positive terms still produce variants
    for variant in variants:
        assert "bad studio" not in variant.key.casefold()
        assert "bad studio" not in variant.query.casefold()
        assert "bad studio" not in variant.source_term.casefold()


def test_a_title_with_only_exclusion_terms_beyond_its_name_still_only_queries_the_name() -> None:
    title = _build_title(name="Nova", exclusions=["Rival Studio"])

    variants = build_query_variants(title, limit=10)

    assert [variant.key for variant in variants] == ["name"]


# ---------------------------------------------------------------------------
# Section 6 — The query plan is deterministic and capped: raising or lowering the cap
# adds or drops the weakest trailing variants rather than reshuffling the rest.
# ---------------------------------------------------------------------------

_CAP_TEST_TITLE_KWARGS: dict[str, Any] = {
    "hashtags": ["#Nova"],
    "aliases": ["Star Fall"],
    "cast": ["Rea Lin", "Ana Kwan"],
    "directors": ["Sam Ito"],
    "music_directors": ["Cy Fox"],
}


def test_five_variant_title_produces_exactly_the_expected_variant_keys_in_order() -> None:
    """Confirms the exact keys `five_variant_title_id` and the responses built around it
    (Sections 2-4) depend on — checked once, directly, rather than assumed at every call
    site."""
    title = _build_title(
        name="Nova",
        hashtags=["#Nova"],
        aliases=["Star Fall"],
        cast=["Rea Lin"],
        directors=["Sam Ito"],
        music_directors=["Cy Fox"],
    )

    variants = build_query_variants(title, limit=5)

    assert tuple(variant.key for variant in variants) == FIVE_VARIANT_KEYS


def test_build_query_variants_is_deterministic_across_repeated_calls() -> None:
    title = _build_title(**_CAP_TEST_TITLE_KWARGS)

    first = build_query_variants(title, limit=5)
    second = build_query_variants(title, limit=5)

    assert [(v.key, v.query, v.source_term) for v in first] == [
        (v.key, v.query, v.source_term) for v in second
    ]


def test_lowering_the_cap_drops_only_the_weakest_trailing_variants() -> None:
    title = _build_title(**_CAP_TEST_TITLE_KWARGS)

    keys_at_five = [variant.key for variant in build_query_variants(title, limit=5)]
    keys_at_three = [variant.key for variant in build_query_variants(title, limit=3)]

    assert keys_at_three == keys_at_five[:3]


def test_raising_the_cap_only_adds_trailing_variants_without_reordering_the_rest() -> None:
    title = _build_title(**_CAP_TEST_TITLE_KWARGS)

    keys_at_five = [variant.key for variant in build_query_variants(title, limit=5)]
    keys_at_six = [variant.key for variant in build_query_variants(title, limit=6)]
    keys_at_eight = [variant.key for variant in build_query_variants(title, limit=8)]

    assert keys_at_six[:5] == keys_at_five
    # Only 6 candidates exist for this identity set, so raising the cap past that adds
    # nothing further rather than inventing variants.
    assert keys_at_eight == keys_at_six


# ---------------------------------------------------------------------------
# Section 6b — Regression: an alias must be anchored by the title's leading anchor
# person exactly the way the `name` variant is, never left bare. A bare alias like
# "Drug Cartel" collects posts about actual drug cartels — the same namesake problem the
# anchor rule exists to prevent, and entity-match precision is this epic's own measured
# gate, not merely a documented preference. The bug was a query style *inferred* from
# the term's type, which let the alias band silently skip the anchor its own comment
# promised it. The fix (`app/services/collection/query_plan.py`) replaces the inference
# with an explicit `_QueryStyle` chosen per band. These tests pin both the fixed literal
# output (so the specific regression cannot return unnoticed) and the band-to-style
# mapping itself (so a *different* band cannot silently lose its style the same way).
# ---------------------------------------------------------------------------


def test_alias_is_anchored_by_the_leading_anchor_person_when_the_title_has_one() -> None:
    """The specific regression, pinned on the literal query string: `alias:drug cartel`
    must not be a bare `"Drug Cartel"` when the title has a director to anchor it."""
    title = _build_title(name="DC", directors=["Lokesh Kanagaraj"], aliases=["Drug Cartel"])

    variants = {variant.key: variant.query for variant in build_query_variants(title, limit=10)}

    assert variants["alias:drug cartel"] == '"Lokesh Kanagaraj Drug Cartel"'


def test_alias_with_no_anchor_term_falls_back_to_the_same_bare_shape_the_name_gets() -> None:
    """With no anchor term at all, the alias is unanchored — but so is the `name`
    variant in that same situation, and the two must stay the same shape so they cannot
    drift apart again the way they did before the fix."""
    title = _build_title(name="Nova", aliases=["Drug Cartel"])

    variants = {variant.key: variant.query for variant in build_query_variants(title, limit=10)}

    assert variants["alias:drug cartel"] == '"Drug Cartel"'
    assert variants["name"] == '"Nova"'


def test_each_bands_query_style_matches_its_documented_shape_end_to_end() -> None:
    """Pins the band-to-style mapping through `build_query_variants` itself — which band
    gets which `_QueryStyle` — rather than only at the `_query_for_term` unit level
    below, so a mistake in `_candidate_variants`' own dispatch would also be caught."""
    title = _build_title(
        name="DC",
        directors=["Lokesh Kanagaraj"],
        hashtags=["#DCFDFS"],
        aliases=["Drug Cartel"],
        cast=["Rukmini"],
    )

    variants = {variant.key: variant.query for variant in build_query_variants(title, limit=10)}

    assert variants["hashtag:dcfdfs"] == "#DCFDFS"  # BARE
    assert variants["alias:drug cartel"] == '"Rukmini Drug Cartel"'  # ANCHORED_TITLE
    assert variants["director:lokesh kanagaraj"] == '"Lokesh Kanagaraj DC"'  # PERSON_WITH_TITLE


def test_query_style_bare_asks_for_the_terms_own_value_with_no_anchor() -> None:
    term = TitleTerm(term_type=TitleTermType.HASHTAG, value="#DCFDFS", normalized_value="dcfdfs")

    query = _query_for_term(term, "DC", ["Lokesh Kanagaraj"], _QueryStyle.BARE)

    assert query == "#DCFDFS"


def test_query_style_anchored_title_anchors_the_terms_own_value_not_the_titles_name() -> None:
    term = TitleTerm(
        term_type=TitleTermType.ALIAS, value="Drug Cartel", normalized_value="drug cartel"
    )

    query = _query_for_term(term, "DC", ["Lokesh Kanagaraj"], _QueryStyle.ANCHORED_TITLE)

    assert query == '"Lokesh Kanagaraj Drug Cartel"'


def test_query_style_person_with_title_pairs_the_terms_own_value_with_the_titles_name() -> None:
    term = TitleTerm(term_type=TitleTermType.CAST, value="Rukmini", normalized_value="rukmini")

    query = _query_for_term(term, "DC", ["Lokesh Kanagaraj"], _QueryStyle.PERSON_WITH_TITLE)

    assert query == '"Rukmini DC"'


# ---------------------------------------------------------------------------
# Section 7 — A cycle always queues its successor: after success, a spend refusal, or a
# crash. A title must never be left with nothing owed to it.
# ---------------------------------------------------------------------------


async def test_a_successful_cycle_queues_its_successor(
    db_session: AsyncSession, five_variant_cycle: _FiveVariantCycle
) -> None:
    assert five_variant_cycle.result.next_run_at is not None
    assert (
        await CollectionRunRepository(db_session).has_pending_for_title(five_variant_cycle.title_id)
        is True
    )


async def test_a_cycle_refused_by_the_spend_policy_still_queues_its_successor(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    transport = SequencedTikhubTransport([_tikhub_response()])
    service = _build_run_service(db_session, transport, spend_policy=_RefusingSpendPolicy())

    result = await service.execute_run(await _pending_run(db_session, title_id))

    assert result.status is CollectionRunStatus.SKIPPED
    assert result.next_run_at is not None
    assert await CollectionRunRepository(db_session).has_pending_for_title(title_id) is True


async def test_a_cycle_that_crashes_still_queues_its_successor(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    service = _build_run_service_with_source(db_session, _CrashingSource())

    result = await service.execute_run(await _pending_run(db_session, title_id))

    assert result.status is CollectionRunStatus.FAILED
    assert result.next_run_at is not None
    assert await CollectionRunRepository(db_session).has_pending_for_title(title_id) is True


# ---------------------------------------------------------------------------
# Section 8 — A run must never be left stuck in `running` after a failure.
# ---------------------------------------------------------------------------


async def test_a_crashed_run_is_finished_as_failed_not_left_running(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    service = _build_run_service_with_source(db_session, _CrashingSource())
    run = await _pending_run(db_session, title_id)
    run_id = run.id

    await service.execute_run(run)

    refreshed = await db_session.get(CollectionRun, run_id)
    assert refreshed is not None
    assert refreshed.status is CollectionRunStatus.FAILED
    assert refreshed.status.is_pending is False
    assert refreshed.finished_at is not None


# ---------------------------------------------------------------------------
# Section 9 — A spend policy that refuses causes zero provider calls.
# ---------------------------------------------------------------------------


async def test_a_spend_policy_refusal_causes_zero_provider_calls(
    db_session: AsyncSession, five_variant_title_id: uuid.UUID
) -> None:
    transport = SequencedTikhubTransport(_five_variant_cycle_responses())
    service = _build_run_service(db_session, transport, spend_policy=_RefusingSpendPolicy())

    result = await service.execute_run(await _pending_run(db_session, five_variant_title_id))

    assert result.status is CollectionRunStatus.SKIPPED
    assert result.mentions_stored == 0
    assert transport.calls == []


# ---------------------------------------------------------------------------
# Section 10 — A platform whose route cannot resolve is tried once per cycle, not once
# per variant, and a cycle where nothing could be collected is `skipped`, never
# `succeeded`.
# ---------------------------------------------------------------------------


async def test_an_unusable_platform_route_is_tried_once_per_cycle_not_once_per_variant(
    db_session: AsyncSession, five_variant_title_id: uuid.UUID
) -> None:
    source = _CountingRefusingSource()
    service = _build_run_service_with_source(db_session, source)

    await service.execute_run(await _pending_run(db_session, five_variant_title_id))

    # Five variants were planned for this title; a working platform would be asked five
    # times. An unusable route is abandoned after the first refusal instead.
    assert source.calls == 1


async def test_a_cycle_where_the_only_platform_is_unusable_is_skipped_not_succeeded(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    source = _CountingRefusingSource()
    service = _build_run_service_with_source(db_session, source)

    result = await service.execute_run(await _pending_run(db_session, title_id))

    assert result.status is CollectionRunStatus.SKIPPED
    assert result.mentions_stored == 0


# ---------------------------------------------------------------------------
# Section 11 — Only one pending run per title: `queue_next_run` and `queue_manual_run`
# both decline while one is already owed, and both work again once it has finished.
# ---------------------------------------------------------------------------


async def test_queue_next_run_declines_while_a_run_is_already_pending(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    title = await TitleRepository(db_session).get_by_id(title_id)
    assert title is not None
    schedule_service = CollectionScheduleService(db_session, FixedCadencePolicy(12))

    declined = await schedule_service.queue_next_run(title, after=datetime.now(UTC))

    assert declined is None
    runs = await CollectionRunRepository(db_session).list_for_title(title_id, limit=10)
    assert len(runs) == 1


async def test_queue_manual_run_declines_while_a_run_is_already_pending(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    title = await TitleRepository(db_session).get_by_id(title_id)
    assert title is not None
    schedule_service = CollectionScheduleService(db_session, FixedCadencePolicy(12))

    declined = await schedule_service.queue_manual_run(title)

    assert declined is None
    runs = await CollectionRunRepository(db_session).list_for_title(title_id, limit=10)
    assert len(runs) == 1


async def test_queue_next_run_succeeds_again_once_the_pending_cycle_has_finished(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    run_repository = CollectionRunRepository(db_session)
    pending = await run_repository.next_pending_for_title(title_id)
    assert pending is not None
    pending.status = CollectionRunStatus.SUCCEEDED
    pending.finished_at = datetime.now(UTC)
    await db_session.flush()

    title = await TitleRepository(db_session).get_by_id(title_id)
    assert title is not None
    schedule_service = CollectionScheduleService(db_session, FixedCadencePolicy(12))
    queued = await schedule_service.queue_next_run(title, after=datetime.now(UTC))

    assert queued is not None
    assert await run_repository.has_pending_for_title(title_id) is True


# ---------------------------------------------------------------------------
# Section 12 — `GET /titles/{id}/collection`: access control and the
# `is_awaiting_first_results`/`is_stalled` states.
# ---------------------------------------------------------------------------


async def test_collection_status_endpoint_returns_404_for_a_non_member_not_403(
    other_api_client: AsyncClient, title_id: uuid.UUID
) -> None:
    """The same posture `TitleService.get_title` takes: a non-member is told the title
    does not exist, never that it exists but is forbidden — which would leak that an
    unannounced title is being tracked at all."""
    response = await other_api_client.get(f"/api/v1/titles/{title_id}/collection")

    assert response.status_code == 404


async def test_collection_status_endpoint_returns_404_for_a_title_that_does_not_exist(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get(f"/api/v1/titles/{uuid.uuid4()}/collection")

    assert response.status_code == 404


async def test_collection_status_is_stalled_once_nothing_is_scheduled_for_the_title(
    db_session: AsyncSession, api_client: AsyncClient, title_id: uuid.UUID
) -> None:
    run_repository = CollectionRunRepository(db_session)
    pending = await run_repository.next_pending_for_title(title_id)
    assert pending is not None
    pending.status = CollectionRunStatus.SUCCEEDED
    pending.finished_at = datetime.now(UTC)
    await db_session.commit()

    response = await api_client.get(f"/api/v1/titles/{title_id}/collection")

    assert response.status_code == 200
    body = response.json()
    assert body["is_stalled"] is True
    assert body["is_awaiting_first_results"] is False
    assert body["next_run_at"] is None


async def test_collection_status_stops_being_awaiting_first_results_once_a_mention_lands(
    db_session: AsyncSession, api_client: AsyncClient, title_id: uuid.UUID
) -> None:
    transport = SequencedTikhubTransport([_tikhub_response("landed-1")])
    service = _build_run_service(db_session, transport)
    await service.execute_run(await _pending_run(db_session, title_id))

    response = await api_client.get(f"/api/v1/titles/{title_id}/collection")

    assert response.status_code == 200
    body = response.json()
    assert body["unsegmented_mention_count"] == 1
    assert body["is_awaiting_first_results"] is False


# ---------------------------------------------------------------------------
# Section 13 — The reprocess corpus walk (E03-S04) survives a mention inserted by a
# concurrent process mid-walk: the exact race `MentionRepository.list_for_title_in_window`
# says its `(collected_at, id)` cursor exists to fix, made reachable for the first time by
# this story's scheduler. Deterministic: the "concurrent" insert happens from inside the
# analyzer double's own call, at a precise, chosen `collected_at`, rather than from real
# concurrency.
# ---------------------------------------------------------------------------


@dataclass
class _ConcurrentInsertAnalyzer(MentionAnalyzer):
    """Stands in for a poll that writes a new mention while a reprocess walk is
    mid-flight. On its first call only, inserts one mention with a `collected_at` that
    sorts strictly between the cursor the walk has just advanced past and the next
    not-yet-visited row — exactly the row a walk paged by a mutable or unordered column
    could lose. Every subsequent call is a plain, successful analysis."""

    session: AsyncSession
    title_id: uuid.UUID
    concurrent_collected_at: datetime
    version_name: str = "concurrent-v1"
    _inserted: bool = field(default=False, init=False)
    calls: list[list[AnalyzableMention]] = field(default_factory=list, init=False)

    @property
    def pipeline_version(self) -> str:
        return self.version_name

    async def analyze(self, mentions: Any) -> list[AnalysisVerdict]:
        batch = list(mentions)
        self.calls.append(batch)
        if not self._inserted:
            self._inserted = True
            concurrent_mention = Mention(
                title_id=self.title_id,
                platform=Platform.X,
                external_id="concurrent-mid-walk",
                author_handle="concurrent_user",
                author_display_name="Concurrent User",
                text="inserted mid-walk by a concurrent poll",
                posted_at=datetime(2026, 1, 1, tzinfo=UTC),
                collected_at=self.concurrent_collected_at,
            )
            self.session.add(concurrent_mention)
            await self.session.flush()
        return [
            AnalysisVerdict(
                mention_id=mention.mention_id,
                detected_language="en",
                language_confidence=0.9,
            )
            for mention in batch
        ]


async def test_reprocess_walk_picks_up_a_mention_inserted_concurrently_mid_walk(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reprocess_service_module, "REPROCESS_BATCH_SIZE", 2)

    organization = Organization(
        name="Sun Pictures",
        slug="sun-pictures-concurrent-walk",
        organization_type=OrganizationType.PRODUCTION_HOUSE,
    )
    db_session.add(organization)
    await db_session.flush()
    title = Title(organization_id=organization.id, name="Nova", release_date=date(2026, 8, 15))
    db_session.add(title)
    await db_session.flush()
    title_id = title.id

    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(3):
        db_session.add(
            Mention(
                title_id=title_id,
                platform=Platform.X,
                external_id=f"pre-existing-{index}",
                author_handle="synthetic_user",
                author_display_name="Synthetic User",
                text=f"pre-existing mention {index}",
                posted_at=start + timedelta(minutes=index),
                collected_at=start + timedelta(seconds=index),
            )
        )
    await db_session.flush()

    # Sorts strictly between the batch-1 cursor (t0+1s, the second pre-existing mention)
    # and the not-yet-visited third one (t0+2s) — the position a mention written by a
    # concurrent poll mid-walk would actually land in.
    concurrent_collected_at = start + timedelta(seconds=1, milliseconds=500)
    analyzer = _ConcurrentInsertAnalyzer(
        session=db_session, title_id=title_id, concurrent_collected_at=concurrent_collected_at
    )
    service = ReprocessService(db_session, analyzer)

    result = await service.reprocess_title(title_id)

    # 3 pre-existing mentions, plus the 1 inserted mid-walk by the analyzer double itself:
    # picked up in the same run, not left for a later one.
    assert result.examined == 4
    assert result.analyzed == 4

    seen_ids = [mention.mention_id for batch in analyzer.calls for mention in batch]
    assert len(seen_ids) == 4
    assert len(set(seen_ids)) == 4


# ---------------------------------------------------------------------------
# Section 14 — Review round 3 (`changes-requested`, two real bugs, both reproduced
# independently by the coordinator). `run_due_cycles` now iterates run *ids* rather than
# the ORM instances `claim_due` returned, reloading each run inside its own iteration: all
# runs in a tick share one session, and a rollback anywhere in it expires every instance
# attached to that session, so a neighbour's handled failure was raising `MissingGreenlet`
# from plain attribute access on a run that had not started yet. `_finish` now commits the
# closed run first, then queues the successor in a *separate* transaction via
# `_queue_successor`, which swallows both `IntegrityError` (benign: another process won
# the race) and any other exception (logged; the run stays closed, honestly, rather than
# rolling the close back with it). A new partial unique index,
# `uq_collection_run_one_pending_per_title`, is what actually guarantees one pending cycle
# per title — the service's own pre-check is only an optimisation on top of it.
# ---------------------------------------------------------------------------


class _PerTitleCadencePolicy(CadencePolicy):
    """A `CadencePolicy` double that returns a different rate per title id — the seam
    needed to make exactly one title in a batch trip the rate validation
    (`polls_per_day=0` is outside its supported range) while its neighbour stays on an
    ordinary rate.

    Armed rather than broken from construction. E03-S02 moved that validation into
    `CadenceDecision`, which is built on *every* enqueue including the first — so a
    permanently broken double would now fail while seeding the queue, before the tick
    these tests are about has even started. The failure under test here is a cadence that
    raises as a *finished* cycle queues its successor, so the double stays healthy until
    the queue is seeded and is armed immediately afterwards."""

    def __init__(self, rates: dict[uuid.UUID, int], *, default_rate: int = 12) -> None:
        self._rates = rates
        self._default_rate = default_rate
        self._is_armed = False

    def arm(self) -> None:
        self._is_armed = True

    async def decide(self, title: Title, *, now: datetime | None = None) -> CadenceDecision:
        rate = self._default_rate
        if self._is_armed:
            rate = self._rates.get(title.id, self._default_rate)
        return CadenceDecision(
            phase=CadencePhase.CAMPAIGN,
            calendar_phase=CadencePhase.CAMPAIGN,
            polls_per_day=rate,
            is_volume_escalated=False,
        )


async def _make_title(
    session: AsyncSession, *, name: str = "Nova", owner: User | None = None
) -> Title:
    """A real, persisted title with its own organization — built directly over the ORM
    rather than through the API, since this section's tests construct their own
    `CollectionRunService` wiring (a per-title cadence, a controlled batch) that the API
    fixtures do not expose. `owner`, when given, is made an `OWNER` member so
    `CollectionStatusService` (which enforces membership) can be read against this title."""
    organization = Organization(
        name="Sun Pictures",
        slug=f"sun-pictures-{uuid.uuid4().hex[:8]}",
        organization_type=OrganizationType.PRODUCTION_HOUSE,
    )
    session.add(organization)
    await session.flush()
    if owner is not None:
        session.add(
            Membership(user_id=owner.id, organization_id=organization.id, role=MembershipRole.OWNER)
        )
    title = Title(organization_id=organization.id, name=name, release_date=date(2026, 8, 15))
    session.add(title)
    await session.flush()
    return title


async def _queue_two_titles_one_with_a_broken_cadence(
    session: AsyncSession, *, broken_title_owner: User | None = None
) -> tuple[uuid.UUID, uuid.UUID, CollectionRunService]:
    """A batch of two due cycles: `broken_title_id`'s cadence returns `polls_per_day=0`,
    which nothing rejects until `_queue_successor` tries to compute its next run while
    closing the cycle — exactly the "cadence that raises" the coordinator described.
    `healthy_title_id` is on an ordinary rate. The broken title is queued to fall due
    first, so `claim_due`'s `ORDER BY scheduled_for` claims and processes it before its
    neighbour — the ordering that let a shared-session rollback poison the neighbour's
    already-loaded instance before the ids-not-instances fix landed.
    """
    broken_title = await _make_title(session, name="Broken", owner=broken_title_owner)
    healthy_title = await _make_title(session, name="Healthy")
    cadence = _PerTitleCadencePolicy({broken_title.id: 0})
    schedule_service = CollectionScheduleService(session, cadence)
    now = datetime.now(UTC)
    await schedule_service.queue_first_run(broken_title, now=now - timedelta(seconds=5))
    await schedule_service.queue_first_run(healthy_title, now=now)
    await session.commit()
    cadence.arm()

    transport = SequencedTikhubTransport([_tikhub_response()])
    settings = Settings(collection_platforms=[Platform.X])
    source = MonidCollectionSource(transport, settings)
    collection_service = CollectionService(session, source)
    run_service = CollectionRunService(
        session, collection_service, schedule_service, UnrestrictedSpendPolicy(), settings
    )
    return broken_title.id, healthy_title.id, run_service


async def test_one_titles_broken_cadence_does_not_abandon_the_others_cycle_in_the_batch(
    db_session: AsyncSession,
) -> None:
    """Task item (a): two titles, one due run each, one given a cadence that raises. The
    healthy title's cycle must complete and get a successor queued regardless — one bad
    title in a batch must not take a good one down with it."""
    (
        broken_title_id,
        healthy_title_id,
        run_service,
    ) = await _queue_two_titles_one_with_a_broken_cadence(db_session)

    results = await run_service.run_due_cycles()

    assert len(results) == 2
    healthy_result = next(result for result in results if result.title_id == healthy_title_id)
    assert healthy_result.status is CollectionRunStatus.SUCCEEDED
    assert healthy_result.next_run_at is not None
    run_repository = CollectionRunRepository(db_session)
    assert await run_repository.has_pending_for_title(healthy_title_id) is True

    # Neither title's run is left `RUNNING` — not even the broken one.
    _ = broken_title_id
    all_runs = (await db_session.execute(select(CollectionRun))).scalars().all()
    assert all(run.status is not CollectionRunStatus.RUNNING for run in all_runs)


async def test_no_run_is_left_running_after_run_due_cycles_returns_even_when_a_successor_fails(
    db_session: AsyncSession,
) -> None:
    """Task item (b). Broader than the assertion embedded in the previous test: every row
    this tick touched, for both titles, is checked — the invariant `_abandon` exists to
    guarantee even on the path where a cycle's own work succeeded and only queuing its
    successor failed."""
    _, _, run_service = await _queue_two_titles_one_with_a_broken_cadence(db_session)

    results = await run_service.run_due_cycles()
    assert len(results) == 2  # sanity: both cycles actually ran

    all_runs = (await db_session.execute(select(CollectionRun))).scalars().all()
    assert all_runs
    assert all(run.status is not CollectionRunStatus.RUNNING for run in all_runs)


async def test_partial_unique_index_refuses_a_second_pending_run_when_two_sessions_race(
    tmp_path: Path,
) -> None:
    """Task item (c). `CollectionScheduleService`'s "is anything pending?" pre-check is
    only an optimisation; this is what actually enforces one pending cycle per title. Two
    independent sessions both read "nothing pending" — the race a worker queuing a
    successor beside an operator's `--title-id` reaches — and both attempt to insert.
    Verified the way the coordinator verified it: on SQLite (here) with two interleaved
    sessions, neither re-checking after the other's commit."""
    db_path = tmp_path / "one_pending_run_race.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as setup_session:
            title = await _make_title(setup_session, name="Nova")
            await setup_session.commit()
            title_id = title.id

        async with session_factory() as session_a, session_factory() as session_b:
            repository_a = CollectionRunRepository(session_a)
            repository_b = CollectionRunRepository(session_b)

            # Both workers check first, and both see nothing pending — the race.
            assert await repository_a.has_pending_for_title(title_id) is False
            assert await repository_b.has_pending_for_title(title_id) is False

            now = datetime.now(UTC)
            repository_a.add(
                CollectionRun(
                    title_id=title_id,
                    status=CollectionRunStatus.QUEUED,
                    trigger=CollectionRunTrigger.SCHEDULED,
                    scheduled_for=now,
                    polls_per_day=12,
                )
            )
            await session_a.commit()

            repository_b.add(
                CollectionRun(
                    title_id=title_id,
                    status=CollectionRunStatus.QUEUED,
                    trigger=CollectionRunTrigger.SCHEDULED,
                    scheduled_for=now,
                    polls_per_day=12,
                )
            )
            with pytest.raises(IntegrityError):
                await session_b.commit()
            await session_b.rollback()

        async with session_factory() as reader_session:
            runs = await CollectionRunRepository(reader_session).list_for_title(title_id, limit=10)
    finally:
        await engine.dispose()

    pending_runs = [run for run in runs if run.status.is_pending]
    assert len(pending_runs) == 1


async def test_a_cycle_whose_successor_cannot_be_queued_still_leaves_the_run_closed_and_stalled(
    db_session: AsyncSession, pilot_user: User
) -> None:
    """Task item (d): the honest version of the failure. The broken title's own cycle did
    real work and must be reported as such — `SUCCEEDED`, not `FAILED` — because nothing
    about collecting for it went wrong; only queuing its successor did, silently and
    internally. The title then reads `is_stalled` on the dashboard, which is exactly what
    it is: nothing is owed to it any more, and only a human (or a later fix to its
    cadence) can fix that."""
    broken_title_id, _, run_service = await _queue_two_titles_one_with_a_broken_cadence(
        db_session, broken_title_owner=pilot_user
    )

    results = await run_service.run_due_cycles()

    broken_result = next(result for result in results if result.title_id == broken_title_id)
    assert broken_result.status is CollectionRunStatus.SUCCEEDED
    assert broken_result.failure_reason is None
    assert broken_result.next_run_at is None

    run_repository = CollectionRunRepository(db_session)
    assert await run_repository.has_pending_for_title(broken_title_id) is False

    # `run_due_cycles` rolled back internally while handling the broken title's own
    # successor-queue failure, which — sharing this one session, the way this test's
    # fixtures do but a real worker and a real API request never do — expired every
    # instance attached to it, `pilot_user` included. A genuine dashboard read always
    # comes through its own, independent session; refreshing here is the honest
    # equivalent of that inside a single shared session, not a workaround for a bug in
    # the service under test.
    await db_session.refresh(pilot_user)
    status = await CollectionStatusService(db_session, FixedCadencePolicy(12)).status_for_title(
        broken_title_id, pilot_user
    )
    assert status.is_stalled is True


async def test_abandon_closes_a_running_run_as_failed_with_the_documented_reason(
    db_session: AsyncSession,
) -> None:
    """Task item (e). `_abandon` is the last-resort path `run_due_cycles` reaches for when
    a run's own completion path raises — reload by id, close as `FAILED`, and say why."""
    title = await _make_title(db_session, name="Nova")
    schedule_service = CollectionScheduleService(db_session, FixedCadencePolicy(12))
    run = await schedule_service.queue_first_run(title)
    await db_session.commit()
    # `_abandon` exists for the state a run is in mid-cycle, not the state it starts in —
    # put it there the way `claim_due` would.
    run.status = CollectionRunStatus.RUNNING
    run.started_at = datetime.now(UTC)
    await db_session.commit()
    run_id = run.id

    transport = SequencedTikhubTransport([_tikhub_response()])
    run_service = _build_run_service(db_session, transport)

    await run_service._abandon(run_id)

    refreshed = await db_session.get(CollectionRun, run_id)
    assert refreshed is not None
    assert refreshed.status is CollectionRunStatus.FAILED
    assert refreshed.failure_reason == ABANDONED_REASON
    assert refreshed.finished_at is not None


# ---------------------------------------------------------------------------
# Section 15 — Review round 4, Finding 1 (`changes-requested`): the variant plan was not
# actually deterministic. `Title.terms` had no `order_by`, so SQL returned rows in no
# defined order — two reads of an *unchanged* identity set could hand terms back
# differently, changing which anchor leads the title's own query and, because the plan is
# capped, which variants exist at all. Section 6's determinism tests built `title.terms`
# as a fixed in-memory Python list and never round-tripped through a database read, so
# they asserted determinism against something that was already deterministic and could
# not have caught this. Fixed two ways: the relationship now declares
# `order_by="TitleTerm.term_type, TitleTerm.normalized_value"` (a total order —
# `uq_title_term_normalized` guarantees no ties), and `query_plan.ordered_identity_terms`
# now sorts explicitly rather than trusting it, because a relationship's `order_by` does
# not apply to a collection already loaded in the session — the write path assigns
# `title.terms` in memory, so a POST response, or a cycle sharing a session with a create,
# would still plan against insertion order.
# ---------------------------------------------------------------------------


async def test_variant_plan_is_deterministic_across_a_real_database_round_trip(
    tmp_path: Path,
) -> None:
    """Task item (a) — the one that matters. An identity set is written, read back
    through `TitleRepository.get_by_id`, and planned; the identical terms are then
    deleted and re-inserted in the reverse physical order — nothing a studio would call a
    change — and read and planned again from a fresh session, so nothing is served from
    an identity map that would mask a real re-query. Both the variant *keys* and the
    `name` variant's query string (which anchor leads) must match exactly.

    This reproduces the reviewer's own finding: three anchor-type terms (cast, director,
    music director), no hashtag or alias, so the entire plan is just the `name` variant
    plus one variant per remaining anchor once the leading one is skipped — and which one
    leads is exactly what unordered rows put at risk.
    """
    db_path = tmp_path / "variant_plan_determinism.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    term_specs = [
        (TitleTermType.CAST, "Rea Lin", "rea lin"),
        (TitleTermType.DIRECTOR, "Sam Ito", "sam ito"),
        (TitleTermType.MUSIC_DIRECTOR, "Cy Fox", "cy fox"),
    ]

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as setup_session:
            title = await _make_title(setup_session, name="Nova")
            title_id = title.id
            for term_type, value, normalized_value in term_specs:
                setup_session.add(
                    TitleTerm(
                        title_id=title_id,
                        term_type=term_type,
                        value=value,
                        normalized_value=normalized_value,
                    )
                )
            await setup_session.commit()

        async with session_factory() as first_read_session:
            first_title = await TitleRepository(first_read_session).get_by_id(title_id)
            assert first_title is not None
            first_plan = build_query_variants(first_title, limit=10)

        # Rewrite the identical identity set in a different physical order: delete every
        # term row and re-insert the same three, reversed.
        async with session_factory() as rewrite_session:
            existing_terms = (
                (
                    await rewrite_session.execute(
                        select(TitleTerm).where(TitleTerm.title_id == title_id)
                    )
                )
                .scalars()
                .all()
            )
            for term in existing_terms:
                await rewrite_session.delete(term)
            await rewrite_session.flush()
            for term_type, value, normalized_value in reversed(term_specs):
                rewrite_session.add(
                    TitleTerm(
                        title_id=title_id,
                        term_type=term_type,
                        value=value,
                        normalized_value=normalized_value,
                    )
                )
            await rewrite_session.commit()

        async with session_factory() as second_read_session:
            second_title = await TitleRepository(second_read_session).get_by_id(title_id)
            assert second_title is not None
            second_plan = build_query_variants(second_title, limit=10)
    finally:
        await engine.dispose()

    assert [variant.key for variant in first_plan] == [variant.key for variant in second_plan]
    first_name_query = next(variant for variant in first_plan if variant.key == "name").query
    second_name_query = next(variant for variant in second_plan if variant.key == "name").query
    assert first_name_query == second_name_query


def test_variant_plan_from_in_memory_terms_is_unaffected_by_their_assignment_order() -> None:
    """Task item (b) — the write path. `TitleService.create_title` assigns `title.terms`
    as a plain Python list, and a relationship's `order_by` only applies to a collection
    SQLAlchemy loads from a query — it never touches a list assigned in memory. This is
    the case the database round-trip above cannot cover: no session, no query, nothing
    for a relationship-level `order_by` to attach to. Two titles built with the identical
    three terms, assigned in opposite physical order, must still plan identically — which
    only holds if `ordered_identity_terms` sorts on its own rather than trusting whatever
    order it was handed.
    """
    reverse_assigned = Title(name="Nova", release_date=date(2026, 8, 15))
    reverse_assigned.id = uuid.uuid4()
    reverse_assigned.terms = [
        TitleTerm(
            term_type=TitleTermType.MUSIC_DIRECTOR, value="Cy Fox", normalized_value="cy fox"
        ),
        TitleTerm(term_type=TitleTermType.DIRECTOR, value="Sam Ito", normalized_value="sam ito"),
        TitleTerm(term_type=TitleTermType.CAST, value="Rea Lin", normalized_value="rea lin"),
    ]

    forward_assigned = Title(name="Nova", release_date=date(2026, 8, 15))
    forward_assigned.id = uuid.uuid4()
    forward_assigned.terms = [
        TitleTerm(term_type=TitleTermType.CAST, value="Rea Lin", normalized_value="rea lin"),
        TitleTerm(term_type=TitleTermType.DIRECTOR, value="Sam Ito", normalized_value="sam ito"),
        TitleTerm(
            term_type=TitleTermType.MUSIC_DIRECTOR, value="Cy Fox", normalized_value="cy fox"
        ),
    ]

    reverse_plan = build_query_variants(reverse_assigned, limit=10)
    forward_plan = build_query_variants(forward_assigned, limit=10)

    assert [variant.key for variant in reverse_plan] == [variant.key for variant in forward_plan]
    reverse_name_query = next(variant for variant in reverse_plan if variant.key == "name").query
    forward_name_query = next(variant for variant in forward_plan if variant.key == "name").query
    assert reverse_name_query == forward_name_query


def test_ordered_identity_terms_sorts_by_term_type_then_normalized_value() -> None:
    """Task item (e): pins `ordered_identity_terms`'s own sort key directly, independent
    of `build_query_variants`' downstream use of it."""
    title = Title(name="Nova", release_date=date(2026, 8, 15))
    title.id = uuid.uuid4()
    title.terms = [
        TitleTerm(
            term_type=TitleTermType.MUSIC_DIRECTOR, value="Cy Fox", normalized_value="cy fox"
        ),
        TitleTerm(term_type=TitleTermType.CAST, value="Zed", normalized_value="zed"),
        TitleTerm(term_type=TitleTermType.CAST, value="Ana", normalized_value="ana"),
        TitleTerm(term_type=TitleTermType.DIRECTOR, value="Sam Ito", normalized_value="sam ito"),
    ]

    ordered = ordered_identity_terms(title)

    assert [(term.term_type, term.normalized_value) for term in ordered] == [
        (TitleTermType.CAST, "ana"),
        (TitleTermType.CAST, "zed"),
        (TitleTermType.DIRECTOR, "sam ito"),
        (TitleTermType.MUSIC_DIRECTOR, "cy fox"),
    ]


def test_ordered_identity_terms_still_drops_exclusions() -> None:
    """Task item (e): the sort must not accidentally resurrect an exclusion — they
    disqualify a post rather than fetching one, and this is the same guarantee
    `test_exclusion_terms_never_appear_as_a_query_variants_key_query_or_source_term`
    (Section 5) depends on at one remove."""
    title = Title(name="Nova", release_date=date(2026, 8, 15))
    title.id = uuid.uuid4()
    title.terms = [
        TitleTerm(term_type=TitleTermType.EXCLUSION, value="Bad Term", normalized_value="bad term"),
        TitleTerm(term_type=TitleTermType.CAST, value="Rea Lin", normalized_value="rea lin"),
    ]

    ordered = ordered_identity_terms(title)

    assert [term.term_type for term in ordered] == [TitleTermType.CAST]


def test_ordered_identity_terms_output_order_is_unaffected_by_input_list_order() -> None:
    """Task item (e): the same "sorts, does not trust" guarantee as the write-path test
    above, exercised directly against `ordered_identity_terms` rather than through the
    full plan — the narrower unit the regression actually lives in."""
    title_a = Title(name="Nova", release_date=date(2026, 8, 15))
    title_a.terms = [
        TitleTerm(term_type=TitleTermType.DIRECTOR, value="Sam Ito", normalized_value="sam ito"),
        TitleTerm(term_type=TitleTermType.CAST, value="Rea Lin", normalized_value="rea lin"),
    ]
    title_b = Title(name="Nova", release_date=date(2026, 8, 15))
    title_b.terms = [
        TitleTerm(term_type=TitleTermType.CAST, value="Rea Lin", normalized_value="rea lin"),
        TitleTerm(term_type=TitleTermType.DIRECTOR, value="Sam Ito", normalized_value="sam ito"),
    ]

    assert [term.normalized_value for term in ordered_identity_terms(title_a)] == [
        term.normalized_value for term in ordered_identity_terms(title_b)
    ]


# ---------------------------------------------------------------------------
# Section 16 — Review round 4, Finding 2: `UnrestrictedSpendPolicy` logged its permissive
# decision at `debug`, invisible at the default `info` level, contradicting its own
# docstring's claim of not being silent. Now `info`.
# ---------------------------------------------------------------------------


async def test_unrestricted_spend_policy_logs_its_permissive_decision_at_info_not_debug() -> None:
    """Task item (c). Asserts the level, not merely that something was logged — the
    whole defect was that the line existed but nobody without verbose logging enabled
    would ever see it.

    Plain `caplog.set_level` cannot observe this by itself: `structlog`'s own filtering
    (`wrapper_class=make_filtering_bound_logger(...)`, configured by `conftest.py`'s
    `LOG_LEVEL=warning` the first time any test builds the app) decides whether a log
    call proceeds *before* any stdlib handler — caplog included — ever sees it, and an
    `info` call sits below that threshold. Worse, `structlog` caches a bound logger on
    its module-level proxy object the first time it is used — and `spend_policy.py`'s
    `_logger` has already been used by the time this test runs, since `UnrestrictedSpendPolicy`
    is the default spend policy every other `CollectionRunService` test in this file
    builds — so reconfiguring `structlog` globally afterwards would not reach it either.
    The module is reloaded to obtain a fresh, not-yet-cached proxy under a temporarily
    lowered filter; both the filter and the module are restored immediately after,
    regardless of outcome, so no other test in the suite is affected by this one having
    run. Sensitivity was confirmed the direct way too: temporarily editing the source
    back to `_logger.debug(...)` and rerunning this test alone fails it, restoring it
    passes again — see the task report.
    """
    original_structlog_config = structlog.get_config()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG))
    try:
        importlib.reload(spend_policy_module)
        with structlog.testing.capture_logs() as captured_events:
            await spend_policy_module.UnrestrictedSpendPolicy().decide(uuid.uuid4())
    finally:
        structlog.configure(**original_structlog_config)
        importlib.reload(spend_policy_module)

    matching_events = [
        entry for entry in captured_events if entry.get("event") == "collection.spend.unrestricted"
    ]
    assert len(matching_events) == 1
    assert matching_events[0]["log_level"] == "info"


# ---------------------------------------------------------------------------
# Section 17 — Review round 4, reviewer's minor observation: `collection_polls_per_day`
# had no bounds, so a typo was only caught per-title-per-cycle, where it is swallowed and
# logged by `_queue_successor` — leaving every title quietly stalled one cycle in. Now
# `Field(ge=MIN_POLLS_PER_DAY, le=MAX_POLLS_PER_DAY)`, so a bad value fails at startup.
# ---------------------------------------------------------------------------


def test_collection_polls_per_day_below_the_minimum_is_rejected_at_settings_construction() -> None:
    """Task item (d)."""
    with pytest.raises(ValidationError):
        Settings(collection_polls_per_day=MIN_POLLS_PER_DAY - 1)


def test_collection_polls_per_day_above_the_maximum_is_rejected_at_settings_construction() -> None:
    with pytest.raises(ValidationError):
        Settings(collection_polls_per_day=MAX_POLLS_PER_DAY + 1)


def test_collection_polls_per_day_at_either_bound_is_accepted() -> None:
    assert Settings(collection_polls_per_day=MIN_POLLS_PER_DAY).collection_polls_per_day == (
        MIN_POLLS_PER_DAY
    )
    assert Settings(collection_polls_per_day=MAX_POLLS_PER_DAY).collection_polls_per_day == (
        MAX_POLLS_PER_DAY
    )


# ---------------------------------------------------------------------------
# Section 18 — Review round 5: `CollectionService._store_and_commit`'s single
# `IntegrityError` retry had zero test coverage anywhere in the suite. It is the code
# that closes the concurrent double-poll risk the epic names explicitly: "a page commits
# as one transaction, so a genuinely concurrent double-poll of the same title can hit the
# `mentions` unique constraint and roll back a whole page including its new items. It
# becomes reachable the moment this story's scheduler exists."
#
# A real write conflict cannot be produced on the shared `conftest` `db_session` fixture
# — every call in a test gets the same open, uncommitted session, so there is no second
# writer to race against. These tests use a file-backed database with genuinely
# independent connections: `session_b`, an ordinary `AsyncSession` running the real
# `CollectionService` under test, and a second, synchronous `SyncSession` bound to a
# separate engine on the same file, standing in for "another poll of this title landing
# concurrently."
#
# Forcing the two to interleave at a precise point — after `session_b` has read which
# ids it already holds, but before it commits its own insert of them — needs a real hook,
# not luck: a `before_flush` event on `session_b`'s underlying sync session fires at
# exactly that boundary. The intervening write only succeeds because the database is put
# into WAL mode, where a reader does not block a concurrent writer's commit; SQLite still
# serializes writers against each other, so the technique only works at points where
# `session_b`'s own transaction has not yet written anything — the first flush of a fresh
# attempt, or the first flush of the retry immediately after `_store_and_commit`'s own
# rollback. That constraint is also what shapes Section (c) below.
# ---------------------------------------------------------------------------


class _FakeCollectionSource(CollectionSource):
    """Returns one fixed page, however many times it is asked — bypasses routing and
    adapters entirely, since this section tests `CollectionService`'s own retry, not how
    a page is fetched."""

    def __init__(self, page: CollectionPage) -> None:
        self._page = page

    async def fetch(
        self, platform: Platform, query: str, *, page: str | None = None, limit: int
    ) -> CollectionPage:
        return self._page


def _racing_normalized_mention(external_id: str) -> NormalizedMention:
    return NormalizedMention(
        platform=Platform.X,
        external_id=external_id,
        text=f"post {external_id}",
        posted_at=datetime(2026, 1, 1, tzinfo=UTC),
        author_handle="racer",
        author_display_name="Racer",
        engagement=MentionEngagement(),
    )


def _racing_page(external_ids: list[str]) -> CollectionPage:
    endpoint = get_endpoint("x.tikhub_search_timeline")
    assert endpoint is not None
    return CollectionPage(
        platform=Platform.X,
        endpoint=endpoint,
        adapter_version="test-retry-v1",
        items=[
            CollectedItem(
                raw_payload={"id": external_id},
                external_id=external_id,
                mention=_racing_normalized_mention(external_id),
            )
            for external_id in external_ids
        ],
        next_page=None,
    )


def _insert_racing_mention(sync_engine: Any, title_id: uuid.UUID, external_id: str) -> None:
    """Stands in for a concurrent poll's own, independently committed write — a second,
    genuinely separate connection to the same file, landing while `session_b` is still
    only holding read locks. Only safe to call from a `before_flush` hook firing at a
    point where `session_b`'s own transaction has not yet written anything itself (see
    this section's header comment) — otherwise SQLite's single-writer rule blocks it."""
    with SyncSession(sync_engine) as sync_session:
        sync_session.add(
            Mention(
                title_id=title_id,
                platform=Platform.X,
                external_id=external_id,
                author_handle="concurrent_poll",
                author_display_name="Concurrent Poll",
                text=f"landed concurrently: {external_id}",
                posted_at=datetime(2026, 1, 1, tzinfo=UTC),
                collected_at=datetime.now(UTC),
            )
        )
        sync_session.commit()


@dataclass
class _RetryRaceHarness:
    title_id: uuid.UUID
    session_b: AsyncSession
    sync_engine: Any
    service_b: CollectionService


async def _build_retry_race_harness(tmp_path: Path, db_name: str) -> tuple[_RetryRaceHarness, Any]:
    """A file-backed database in WAL mode, a title, and a `CollectionService` (`session_b`)
    ready to collect a page — plus the independent sync engine used to race it. Returns
    the harness and the async engine (kept open by the caller for the test's duration)."""
    db_path = tmp_path / db_name
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        # WAL: a reader does not block a concurrent writer's commit, which is what lets
        # the independent racing write land while `session_b` still only holds read
        # locks from its own "what do I already know" query.
        await connection.exec_driver_sql("PRAGMA journal_mode=WAL")

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    sync_engine = create_engine(f"sqlite:///{db_path}", future=True)

    async with session_factory() as setup_session:
        title = await _make_title(setup_session, name="Nova")
        title_id = title.id
        await setup_session.commit()

    session_b = session_factory()
    service_b = CollectionService(session_b, _FakeCollectionSource(_racing_page([])))
    harness = _RetryRaceHarness(
        title_id=title_id, session_b=session_b, sync_engine=sync_engine, service_b=service_b
    )
    return harness, engine


async def test_a_concurrent_double_poll_retries_once_and_lands_exactly_the_new_posts(
    tmp_path: Path,
) -> None:
    """Task item (a) — the one that matters — plus (d). `session_b` collects a page
    containing T1, T2, T3. Precisely as `session_b` is about to flush that insert (having
    already read "nothing is known yet"), an independent connection commits T1 first —
    the concurrent double-poll the epic names. `session_b`'s own commit must then fail,
    retry once, and land exactly the two genuinely new posts, with `stored`/`already_known`
    reflecting the *retry's* recomputation, not the doomed first attempt's (which would
    have reported `stored=3, already_known=0` — wrong on both counts).
    """
    harness, engine = await _build_retry_race_harness(tmp_path, "retry_lands_the_page.sqlite3")
    fire_count = 0

    def _race_in_t1(session: Any, flush_context: Any, instances: Any) -> None:
        nonlocal fire_count
        fire_count += 1
        if fire_count == 1:
            _insert_racing_mention(harness.sync_engine, harness.title_id, "T1")

    event.listen(harness.session_b.sync_session, "before_flush", _race_in_t1)
    try:
        harness.service_b._source = _FakeCollectionSource(_racing_page(["T1", "T2", "T3"]))
        result = await harness.service_b.collect_page(
            harness.title_id, Platform.X, "query", limit=20
        )
    finally:
        event.remove(harness.session_b.sync_session, "before_flush", _race_in_t1)
        await harness.session_b.close()

    try:
        # Task (d): the counts reported are the retry's recomputed ones.
        assert result.stored == 2
        assert result.already_known == 1

        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with session_factory() as reader_session:
            mentions = (
                (
                    await reader_session.execute(
                        select(Mention).where(Mention.title_id == harness.title_id)
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()
        harness.sync_engine.dispose()

    external_ids = [mention.external_id for mention in mentions]
    assert sorted(external_ids) == ["T1", "T2", "T3"]
    assert len(external_ids) == len(set(external_ids)) == 3


async def test_a_second_integrity_error_on_the_retry_propagates_instead_of_looping(
    tmp_path: Path,
) -> None:
    """Task item (b). The retry is a single, bounded attempt — not a loop. A second,
    independent write lands again, this time between the retry's own fresh read and its
    commit, conflicting on T2 exactly the way the first race conflicted on T1. Nothing in
    `_store_and_commit` wraps the retry itself in another `except IntegrityError`, so this
    must raise rather than return a silently-wrong result.

    Asserting only `pytest.raises(IntegrityError)` would not actually distinguish a
    bounded retry from no retry at all — deleting the retry entirely also raises
    `IntegrityError`, just on the first collision instead of the second, and the
    sensitivity check in the task report confirms this test's raw shape alone does not
    move. `fire_count` closes that gap: it can only reach 2 if `_store_and_commit` called
    `_store` a second time after the first failure, so asserting it proves the retry was
    genuinely attempted before this failed a second time.
    """
    harness, engine = await _build_retry_race_harness(tmp_path, "retry_is_bounded.sqlite3")
    fire_count = 0

    def _race_in_t1_then_t2(session: Any, flush_context: Any, instances: Any) -> None:
        nonlocal fire_count
        fire_count += 1
        if fire_count == 1:
            _insert_racing_mention(harness.sync_engine, harness.title_id, "T1")
        elif fire_count == 2:
            # The retry's own first flush — the only other point where `session_b`'s
            # transaction has not yet written anything itself (see section header).
            _insert_racing_mention(harness.sync_engine, harness.title_id, "T2")

    event.listen(harness.session_b.sync_session, "before_flush", _race_in_t1_then_t2)
    try:
        harness.service_b._source = _FakeCollectionSource(_racing_page(["T1", "T2", "T3"]))
        with pytest.raises(IntegrityError):
            await harness.service_b.collect_page(harness.title_id, Platform.X, "query", limit=20)
    finally:
        event.remove(harness.session_b.sync_session, "before_flush", _race_in_t1_then_t2)
        await harness.session_b.close()
        await engine.dispose()
        harness.sync_engine.dispose()

    # Proves the retry was actually attempted (and hit T2's conflict) rather than the
    # first collision alone having propagated with no retry ever happening.
    assert fire_count == 2


async def test_an_unresolved_second_conflict_leaves_no_partial_or_silently_absorbed_data(
    tmp_path: Path,
) -> None:
    """Task item (c). The retry exists for one cause — an id it did not yet know about
    when it started. When a second, independent write defeats the retry too, the failure
    must actually surface rather than be papered over: nothing session_b was trying to
    store (T3, never raced against) is left half-written or silently reported as stored,
    and the two rows genuinely present are exactly the two the independent writer put
    there — not a mixture that would suggest the exception was swallowed somewhere on the
    way out.
    """
    harness, engine = await _build_retry_race_harness(
        tmp_path, "retry_second_conflict_not_absorbed.sqlite3"
    )
    fire_count = 0

    def _race_in_t1_then_t2(session: Any, flush_context: Any, instances: Any) -> None:
        nonlocal fire_count
        fire_count += 1
        if fire_count == 1:
            _insert_racing_mention(harness.sync_engine, harness.title_id, "T1")
        elif fire_count == 2:
            _insert_racing_mention(harness.sync_engine, harness.title_id, "T2")

    event.listen(harness.session_b.sync_session, "before_flush", _race_in_t1_then_t2)
    try:
        harness.service_b._source = _FakeCollectionSource(_racing_page(["T1", "T2", "T3"]))
        with pytest.raises(IntegrityError):
            await harness.service_b.collect_page(harness.title_id, Platform.X, "query", limit=20)
    finally:
        event.remove(harness.session_b.sync_session, "before_flush", _race_in_t1_then_t2)
        await harness.session_b.close()

    try:
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with session_factory() as reader_session:
            mentions = (
                (
                    await reader_session.execute(
                        select(Mention).where(Mention.title_id == harness.title_id)
                    )
                )
                .scalars()
                .all()
            )
            payloads = (
                (
                    await reader_session.execute(
                        select(MentionRawPayload).where(
                            MentionRawPayload.title_id == harness.title_id
                        )
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()
        harness.sync_engine.dispose()

    # Exactly what the two independent, successful writes put there — T1 and T2, each
    # once. T3, which only `session_b`'s own failed attempt ever knew about, is absent:
    # its work was fully rolled back, not partially kept.
    assert sorted(mention.external_id for mention in mentions) == ["T1", "T2"]
    assert payloads == []

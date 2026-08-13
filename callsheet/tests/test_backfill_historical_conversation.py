"""Tests for E03-S03 — Backfill the weeks before I signed up, so my trailer launch isn't a
blank spot.

Story: stories/E03-agentic-collection-layer/E03-S03-backfill-historical-conversation.md
Epic: stories/E03-agentic-collection-layer/EPIC.md

The story has exactly one Gherkin scenario ("Owner backfills from the trailer launch date
onwards"), with four Given clauses, one When and one Then. Each maps to exactly one section
below, named so the mapping is obvious:

  - Given 1, "my title was created after my trailer had already launched" -> Section 1.
    The persona's whole premise: the range this story exists for necessarily predates the
    title's own existence in the product. The service must gate a range only against "now",
    never against when the title was created — otherwise the feature could not do the one
    thing it is for.
  - Given 2, "the Title Dashboard offers a 'Backfill history' action with a date range" ->
    Section 2. The backend correlate of that action: `POST .../backfills` accepts a range
    and queues a request from it.
  - Given 3, "the backfill screen shows the estimated cost and page depth before I confirm"
    -> Section 3. `POST .../backfills/estimate` returns both figures and — the other half of
    "before I confirm" — writes nothing: no backfill row exists afterwards.
  - Given 4, "the estimate is derived from PER_CALL pricing and a hard page cap" -> Section
    4. Pins the arithmetic directly against `estimate_backfill`: the quote is exactly
    `variants x page_cap x per_call_price`, and raising the cap raises the quote by the same
    factor, because on a PER_CALL endpoint the cap is the only lever there is.
  - When, "I select a date range starting at my trailer launch and confirm the backfill" ->
    Section 5. Confirming stamps the row with exactly what was quoted — "nothing is spent
    before somebody sees the price" is only true if the confirmed number cannot drift from
    the number the receipt later carries.
  - Then, "historical mentions in that range are collected and merged into my existing trend
    charts, marked as backfilled, without duplicating anything already collected" -> Section
    6. Runs a real backfill through `CollectionBackfillRunner` against a title that already
    holds one mention from an ordinary live poll: the new historical posts land marked
    `is_backfilled=True` and read back through the same `MentionRepository` every chart
    reads, the pre-existing post is neither duplicated nor relabelled, and the run reports
    the range as fully covered.

Sections 7-11 are the task's own five, chosen at the seams most likely to be wrong:

  - Section 7 — `CollectionWindow.exclusive_end_day`'s rounding: a range ending mid-day
    must not lose that day, and a range already ending at midnight must not gain one it
    was never asked for.
  - Section 8 — the naive/aware trap this codebase has already paid for once (E03-S04):
    SQLite hands a stored `requested_from` back naive, while the depth actually reached is
    always aware. Loads a `CollectionBackfill` fresh from a file-backed database — not a
    Python object that happens to already carry a timezone — before exercising the
    comparison `_is_depth_limited` makes.
  - Section 9 — `is_depth_limited` when the walk reached nothing at all, and when the
    backfill never ran (`SKIPPED`): both must read as depth-limited, never as complete
    coverage of a range nobody actually searched.
  - Section 10 — `has_reached_page_cap`, on the two ways a walk can stop short: the product's
    own cap binding first, against the provider running out of pages first. Only one of
    those is something an operator can change, so the row must say which happened.
  - Section 11 — one pending backfill per title, forced by a genuine race: two independent
    sessions that both observe "nothing pending" before either commits, so the partial
    unique index — not the service's own check — is what stops the second write. Not a
    mocked exception.

No test calls Monid. Every transport double below is scripted in-process and never leaves
it. Section 6 mirrors the real captures' shape (a tikhub timeline item) but uses synthetic
posts with controlled `posted_at` values, because this story is about the backfill *walk*
mechanics — window coverage, depth, dedupe against a pre-existing mention — not about one
provider's payload quirks, which `test_provider_agnostic_collection_interface.py` already
covers against the committed fixtures.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.collection_endpoints import PriceModel, get_endpoint
from app.core.config import Settings, get_settings
from app.core.platforms import Platform
from app.models import Base
from app.models.collection_backfill import CollectionBackfill, CollectionBackfillStatus
from app.models.mention import Mention
from app.models.organization import Organization, OrganizationType
from app.models.title import Title
from app.repositories.collection_backfill_repository import CollectionBackfillRepository
from app.repositories.mention_repository import MentionRepository
from app.services.collection.adapters.base import ProviderRequest
from app.services.collection.backfill_cost import estimate_backfill
from app.services.collection.monid_source import MonidCollectionSource, MonidTransport
from app.services.collection.source import CollectionWindow
from app.services.collection.spend_policy import UnrestrictedSpendPolicy
from app.services.collection_backfill_runner import (
    CollectionBackfillRunner,
    _BackfillTotals,
)
from app.services.collection_backfill_service import CollectionBackfillService
from app.services.collection_service import CollectionService

# ---------------------------------------------------------------------------
# Section 0 — Fixtures and helpers.
# ---------------------------------------------------------------------------

ORGANIZATIONS_URL = "/api/v1/organizations"

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


def _organization_payload(*, slug: str) -> dict[str, Any]:
    return {"name": "Sun Pictures", "slug": slug, "organization_type": "production_house"}


async def _create_backfill_title(
    api_client: AsyncClient, *, name: str = "Nova", slug: str = "sun-pictures"
) -> uuid.UUID:
    org_response = await api_client.post(ORGANIZATIONS_URL, json=_organization_payload(slug=slug))
    assert org_response.status_code == 201, org_response.text
    organization_id = org_response.json()["id"]

    title_response = await api_client.post(
        f"{ORGANIZATIONS_URL}/{organization_id}/titles",
        json={**DEFAULT_TITLE_PAYLOAD, "name": name},
    )
    assert title_response.status_code == 201, title_response.text
    return uuid.UUID(title_response.json()["id"])


@pytest.fixture
async def title_id(api_client: AsyncClient) -> uuid.UUID:
    """A single title, owned by `pilot_user` — the shared case for tests that only need
    one title with one query variant ("name")."""
    return await _create_backfill_title(api_client)


def _x_timestamp(when: datetime) -> str:
    """X's legacy timestamp format, the one both adapters emit (see payload_values.py)."""
    return when.strftime("%a %b %d %H:%M:%S %z %Y")


def _tikhub_item(tweet_id: str, posted_at: datetime, *, text: str = "a post") -> dict[str, Any]:
    """A synthetic tikhub timeline item, real enough for `TikhubXSearchAdapter.to_mention`
    to succeed — the same principle `test_collection_starts_and_counts_once.py` uses for
    its own synthetic items, since this story is about walk mechanics rather than payload
    fidelity (already covered elsewhere against the committed captures)."""
    return {
        "type": "tweet",
        "tweet_id": tweet_id,
        "screen_name": "someuser",
        "text": text,
        "created_at": _x_timestamp(posted_at),
    }


class _ScriptedTransport(MonidTransport):
    """Returns one scripted response per call, in the order given. Spends nothing — a real
    Monid call never happens. Raises if asked for more calls than it was scripted for,
    because every test using it knows exactly how many pages its own walk should fetch, and
    an extra call is a bug worth failing loudly on rather than silently reusing a response.
    """

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, ProviderRequest]] = []

    async def run(self, endpoint: Any, request: ProviderRequest) -> Any:
        index = len(self.calls)
        self.calls.append((endpoint.key, request))
        if index >= len(self._responses):
            raise AssertionError("no more scripted responses — the walk made an unexpected call")
        return self._responses[index]


def _build_runner(
    session: AsyncSession, transport: MonidTransport, *, settings: Settings | None = None
) -> CollectionBackfillRunner:
    settings = settings or Settings()
    source = MonidCollectionSource(transport, settings)
    collection_service = CollectionService(session, source)
    return CollectionBackfillRunner(
        session, collection_service, UnrestrictedSpendPolicy(), settings
    )


# ---------------------------------------------------------------------------
# Section 1 — Given: my title was created after my trailer had already launched.
#
# The range this scenario asks for necessarily predates the title's own existence — that
# lag is the entire reason backfill exists. The service must gate the range only against
# "now", never against when the title itself was created.
# ---------------------------------------------------------------------------


async def test_given_a_title_created_after_its_trailer_already_launched_can_still_backfill_it(
    db_session: AsyncSession, title_id: uuid.UUID, pilot_user: Any
) -> None:
    service = CollectionBackfillService(db_session, Settings())
    now = datetime.now(UTC)
    trailer_launch = now - timedelta(days=90)
    campaign_end = now - timedelta(days=60)

    quote = await service.quote(
        title_id,
        pilot_user,
        requested_from=trailer_launch,
        requested_until=campaign_end,
        now=now,
    )

    assert quote.requested_from == trailer_launch
    assert quote.estimate.can_collect_anything


# ---------------------------------------------------------------------------
# Section 2 — Given: the Title Dashboard offers a "Backfill history" action with a date
# range. The backend correlate: the create route accepts a range and queues it.
# ---------------------------------------------------------------------------


async def test_given_the_backfill_action_accepts_a_date_range_and_queues_a_request(
    api_client: AsyncClient, title_id: uuid.UUID
) -> None:
    now = datetime.now(UTC)
    payload = {
        "requested_from": (now - timedelta(days=50)).isoformat(),
        "requested_until": (now - timedelta(days=20)).isoformat(),
    }

    response = await api_client.post(f"/api/v1/titles/{title_id}/backfills", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert datetime.fromisoformat(body["requested_from"]) == datetime.fromisoformat(
        payload["requested_from"]
    )
    assert datetime.fromisoformat(body["requested_until"]) == datetime.fromisoformat(
        payload["requested_until"]
    )
    assert body["page_cap"] == get_settings().collection_backfill_max_pages


# ---------------------------------------------------------------------------
# Section 3 — Given: the backfill screen shows the estimated cost and page depth before I
# confirm. The estimate route answers both, and — the other half of "before I confirm" —
# writes nothing.
# ---------------------------------------------------------------------------


async def test_given_the_estimate_shows_cost_and_page_depth_and_spends_and_writes_nothing(
    api_client: AsyncClient, db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    now = datetime.now(UTC)
    payload = {
        "requested_from": (now - timedelta(days=60)).isoformat(),
        "requested_until": (now - timedelta(days=30)).isoformat(),
    }

    response = await api_client.post(f"/api/v1/titles/{title_id}/backfills/estimate", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["max_cost_usd"] > 0
    assert body["pages_per_query"] == get_settings().collection_backfill_max_pages
    assert body["platforms"][0]["price_model"] == "per_call"

    count = await CollectionBackfillRepository(db_session).count_for_title(title_id)
    assert count == 0


# ---------------------------------------------------------------------------
# Section 4 — Given: the estimate is derived from PER_CALL pricing and a hard page cap.
# Pinned directly against `estimate_backfill`: the quote is exactly
# `variants x page_cap x per_call_price`, and doubling the cap doubles the quote.
# ---------------------------------------------------------------------------


def test_given_the_estimate_is_derived_from_per_call_pricing_and_the_hard_page_cap() -> None:
    x_endpoint = get_endpoint("x.tikhub_search_timeline")
    assert x_endpoint is not None
    assert x_endpoint.price_model is PriceModel.PER_CALL

    estimate_at_five_pages = estimate_backfill(
        variant_count=3, settings=Settings(collection_backfill_max_pages=5)
    )
    estimate_at_ten_pages = estimate_backfill(
        variant_count=3, settings=Settings(collection_backfill_max_pages=10)
    )

    assert estimate_at_five_pages.max_calls == 3 * 5
    assert estimate_at_five_pages.max_cost_usd == pytest.approx(3 * 5 * x_endpoint.unit_price_usd)
    assert estimate_at_five_pages.platforms[0].price_model == str(PriceModel.PER_CALL)
    # On a PER_CALL endpoint the cap is the only lever, so doubling it must double the
    # quote exactly — concept note §7 rule 2, made testable.
    assert estimate_at_ten_pages.max_cost_usd == pytest.approx(
        estimate_at_five_pages.max_cost_usd * 2
    )


# ---------------------------------------------------------------------------
# Section 5 — When: I select a date range starting at my trailer launch and confirm the
# backfill. Confirming stamps the row with exactly what was quoted.
# ---------------------------------------------------------------------------


async def test_when_confirming_a_range_starting_at_the_trailer_launch_queues_it_at_the_quoted_price(
    db_session: AsyncSession, title_id: uuid.UUID, pilot_user: Any
) -> None:
    service = CollectionBackfillService(db_session, Settings())
    now = datetime.now(UTC)
    trailer_launch = now - timedelta(days=45)
    campaign_end = now - timedelta(days=1)

    quote = await service.quote(
        title_id, pilot_user, requested_from=trailer_launch, requested_until=campaign_end, now=now
    )
    backfill = await service.request_backfill(
        title_id, pilot_user, requested_from=trailer_launch, requested_until=campaign_end, now=now
    )

    assert backfill.requested_from == trailer_launch
    assert backfill.requested_until == campaign_end
    assert backfill.status is CollectionBackfillStatus.QUEUED
    # "Nothing is spent before somebody sees the price": the row is stamped with exactly
    # the numbers the quote showed, not a number recomputed at confirm time.
    assert backfill.page_cap == quote.estimate.pages_per_query
    assert backfill.estimated_calls == quote.estimate.max_calls
    assert backfill.estimated_max_cost_usd == pytest.approx(quote.estimate.max_cost_usd)


# ---------------------------------------------------------------------------
# Section 6 — Then: historical mentions in that range are collected and merged into my
# existing trend charts, marked as backfilled, without duplicating anything already
# collected.
# ---------------------------------------------------------------------------


async def test_then_historical_mentions_merge_marked_backfilled_and_unduplicated(
    db_session: AsyncSession, title_id: uuid.UUID, pilot_user: Any
) -> None:
    now = datetime.now(UTC)
    requested_from = now - timedelta(days=45)
    requested_until = now - timedelta(days=5)

    # A post this title already holds from an ordinary live poll, collected before the
    # backfill was ever requested. The backfill must leave it exactly as it is.
    existing_mention = Mention(
        title_id=title_id,
        platform=Platform.X,
        external_id="already-live",
        author_handle="someuser",
        author_display_name="Some User",
        text="Already collected live.",
        posted_at=now - timedelta(days=20),
        hashtags=[],
        collected_at=now,
        is_backfilled=False,
    )
    db_session.add(existing_mention)
    await db_session.commit()

    service = CollectionBackfillService(db_session, Settings())
    await service.request_backfill(
        title_id,
        pilot_user,
        requested_from=requested_from,
        requested_until=requested_until,
        now=now,
    )

    # One page: the same live-collected post again (must not be duplicated or
    # relabelled), a new historical post inside the range, and one old enough to prove the
    # walk actually reached back to — and past — the start of the requested range.
    response = {
        "status": "ok",
        "timeline": [
            _tikhub_item("already-live", now - timedelta(days=20)),
            _tikhub_item("hist-1", now - timedelta(days=30)),
            _tikhub_item("hist-2", now - timedelta(days=46)),
        ],
        "next_cursor": None,
    }
    transport = _ScriptedTransport([response])
    runner = _build_runner(db_session, transport)

    results = await runner.run_queued_backfills()

    assert len(results) == 1
    result = results[0]
    assert result.status is CollectionBackfillStatus.SUCCEEDED
    assert result.mentions_stored == 2
    assert result.mentions_already_known == 1
    assert result.is_depth_limited is False

    mention_repository = MentionRepository(db_session)
    mentions = await mention_repository.list_for_title(title_id, limit=10)
    assert await mention_repository.count_for_title(title_id) == 3
    # Merged into the same read every chart uses — there is no separate backfill corpus.
    assert {mention.external_id for mention in mentions} == {"already-live", "hist-1", "hist-2"}

    by_external_id = {mention.external_id: mention for mention in mentions}
    assert by_external_id["already-live"].is_backfilled is False
    assert by_external_id["hist-1"].is_backfilled is True
    assert by_external_id["hist-2"].is_backfilled is True


# ---------------------------------------------------------------------------
# Section 7 — `CollectionWindow.exclusive_end_day`: a range ending mid-day must not lose
# that day; a range already ending at midnight must not gain one it was never asked for.
# ---------------------------------------------------------------------------


def test_exclusive_end_day_rounds_a_mid_day_end_up_but_leaves_a_midnight_end_untouched() -> None:
    mid_day_window = CollectionWindow(
        posted_from=datetime(2026, 8, 1, tzinfo=UTC),
        posted_until=datetime(2026, 8, 13, 14, 30, tzinfo=UTC),
    )
    midnight_window = CollectionWindow(
        posted_from=datetime(2026, 8, 1, tzinfo=UTC),
        posted_until=datetime(2026, 8, 13, 0, 0, tzinfo=UTC),
    )

    # Truncating "today, mid-afternoon" to a day would silently drop today — the commonest
    # range anyone asks for ("up to now").
    assert mid_day_window.exclusive_end_day == date(2026, 8, 14)
    # An end that already lands exactly on a day boundary must not be pushed a day further
    # than what was asked for.
    assert midnight_window.exclusive_end_day == date(2026, 8, 13)


# ---------------------------------------------------------------------------
# Section 8 — Regression seam: SQLite hands a stored `requested_from` back naive, while the
# depth actually reached is always aware (straight from `parse_x_timestamp`). This already
# bit E03-S04 once (a reprocess reported every mention as changed on every run). Loads a
# `CollectionBackfill` fresh from a file-backed database, not a Python object that happens
# to already carry a timezone, before exercising the exact comparison `_is_depth_limited`
# makes.
# ---------------------------------------------------------------------------


async def test_is_depth_limited_compares_a_naive_requested_from_from_sqlite_against_an_aware_reach(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "backfill_naive_aware.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    requested_from = datetime.now(UTC) - timedelta(days=40)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as writer_session:
            organization = Organization(
                name="Sun Pictures",
                slug="sun-pictures-naive-aware",
                organization_type=OrganizationType.PRODUCTION_HOUSE,
            )
            writer_session.add(organization)
            await writer_session.flush()
            title = Title(
                organization_id=organization.id, name="DC", release_date=date(2026, 8, 15)
            )
            writer_session.add(title)
            await writer_session.flush()
            backfill = CollectionBackfill(
                title_id=title.id,
                requested_from=requested_from,
                requested_until=requested_from + timedelta(days=30),
                status=CollectionBackfillStatus.SUCCEEDED,
                page_cap=5,
            )
            writer_session.add(backfill)
            await writer_session.commit()
            backfill_id = backfill.id

        async with session_factory() as reader_session:
            loaded = await CollectionBackfillRepository(reader_session).get_by_id(backfill_id)
            assert loaded is not None
            # The bug's precondition: SQLite hands this attribute back with no tzinfo,
            # unlike the Python object that was written.
            assert loaded.requested_from.tzinfo is None

            # Aware, exactly the way a real page's oldest post arrives via
            # `parse_x_timestamp`. One day past `requested_from`, so the range was fully
            # covered — a comparison that raises `TypeError` on naive-vs-aware would fail
            # this test outright rather than merely computing the wrong answer.
            totals = _BackfillTotals(earliest_posted_at=requested_from - timedelta(days=1))
            result = CollectionBackfillRunner._is_depth_limited(
                loaded, totals, CollectionBackfillStatus.SUCCEEDED
            )
    finally:
        await engine.dispose()

    assert result is False


# ---------------------------------------------------------------------------
# Section 9 — `is_depth_limited` when the walk reached nothing at all, and when the
# backfill never ran at all (`SKIPPED`). Both must read as depth-limited, never as
# complete coverage of a range nobody actually searched.
# ---------------------------------------------------------------------------


def test_is_depth_limited_is_true_when_nothing_was_reached_and_when_the_backfill_was_skipped() -> (
    None
):
    requested_from = datetime(2026, 6, 1, tzinfo=UTC)
    backfill = CollectionBackfill(
        title_id=uuid.uuid4(),
        requested_from=requested_from,
        requested_until=requested_from + timedelta(days=30),
        page_cap=5,
    )

    # The walk ran to completion but nothing normalised on any page — no post means no
    # evidence the search reached back at all.
    empty_totals = _BackfillTotals()
    assert (
        CollectionBackfillRunner._is_depth_limited(
            backfill, empty_totals, CollectionBackfillStatus.SUCCEEDED
        )
        is True
    )

    # A SKIPPED backfill never ran (spend policy refused, or nothing was collectable) —
    # depth-limited by definition, whatever `totals` happens to hold, so a skipped request
    # cannot render as complete coverage of a range nobody searched.
    reached_totals = _BackfillTotals(earliest_posted_at=requested_from - timedelta(days=1))
    assert (
        CollectionBackfillRunner._is_depth_limited(
            backfill, reached_totals, CollectionBackfillStatus.SKIPPED
        )
        is True
    )


# ---------------------------------------------------------------------------
# Section 10 — `has_reached_page_cap` on the two ways a walk can stop short: the product's
# own cap binding first, against the provider running out of pages first. Only one of
# those is something an operator can change, so the row must say which happened.
# ---------------------------------------------------------------------------


async def test_has_reached_page_cap_separates_our_cap_from_the_provider_running_out(
    db_session: AsyncSession, api_client: AsyncClient, pilot_user: Any
) -> None:
    now = datetime.now(UTC)
    requested_from = now - timedelta(days=100)
    requested_until = now - timedelta(days=90)
    # Always inside the range and never close enough to `requested_from` to look like the
    # walk covered it — the only two stopping conditions left in play are the cap and the
    # provider running out.
    item_posted_at = now - timedelta(days=95)

    # Scenario A: the provider has more pages on offer at every page this walk asks for,
    # but the backfill's own cap of 2 stops it first.
    capped_title_id = await _create_backfill_title(api_client, name="Capped", slug="capped-co")
    capped_service = CollectionBackfillService(
        db_session, Settings(collection_backfill_max_pages=2)
    )
    capped_backfill = await capped_service.request_backfill(
        capped_title_id,
        pilot_user,
        requested_from=requested_from,
        requested_until=requested_until,
        now=now,
    )
    capped_transport = _ScriptedTransport(
        [
            {
                "status": "ok",
                "timeline": [_tikhub_item("cap-a", item_posted_at)],
                "next_cursor": "more-1",
            },
            {
                "status": "ok",
                "timeline": [_tikhub_item("cap-b", item_posted_at)],
                "next_cursor": "more-2",
            },
        ]
    )
    capped_result = await _build_runner(db_session, capped_transport).execute(capped_backfill)

    assert capped_result.pages_fetched == 2
    assert capped_result.has_reached_page_cap is True
    assert capped_result.is_depth_limited is True

    # Scenario B: the same shape, but the provider itself runs out of pages before the
    # (much higher) cap could ever bind.
    exhausted_title_id = await _create_backfill_title(
        api_client, name="Exhausted", slug="exhausted-co"
    )
    exhausted_service = CollectionBackfillService(
        db_session, Settings(collection_backfill_max_pages=5)
    )
    exhausted_backfill = await exhausted_service.request_backfill(
        exhausted_title_id,
        pilot_user,
        requested_from=requested_from,
        requested_until=requested_until,
        now=now,
    )
    exhausted_transport = _ScriptedTransport(
        [
            {
                "status": "ok",
                "timeline": [_tikhub_item("run-a", item_posted_at)],
                "next_cursor": "more-1",
            },
            {
                "status": "ok",
                "timeline": [_tikhub_item("run-b", item_posted_at)],
                "next_cursor": None,
            },
        ]
    )
    exhausted_result = await _build_runner(db_session, exhausted_transport).execute(
        exhausted_backfill
    )

    assert exhausted_result.pages_fetched == 2
    assert exhausted_result.has_reached_page_cap is False
    assert exhausted_result.is_depth_limited is True


# ---------------------------------------------------------------------------
# Section 11 — One pending backfill per title, forced by a genuine race: two independent
# sessions, each having observed "nothing pending" before either commits, both insert a
# QUEUED backfill for the same title. The partial unique index — not the service's own
# check — is what stops the second write. Not a mocked exception.
# ---------------------------------------------------------------------------


async def test_one_pending_backfill_per_title_is_enforced_by_a_genuine_race_between_two_sessions(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "backfill_pending_race.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as setup_session:
            organization = Organization(
                name="Sun Pictures",
                slug="sun-pictures-race",
                organization_type=OrganizationType.PRODUCTION_HOUSE,
            )
            setup_session.add(organization)
            await setup_session.flush()
            title = Title(
                organization_id=organization.id, name="DC", release_date=date(2026, 8, 15)
            )
            setup_session.add(title)
            await setup_session.commit()
            title_id = title.id

        now = datetime.now(UTC)
        requested_from = now - timedelta(days=40)
        requested_until = now - timedelta(days=10)

        session_a = session_factory()
        session_b = session_factory()
        try:
            repository_a = CollectionBackfillRepository(session_a)
            repository_b = CollectionBackfillRepository(session_b)

            # The actual race: neither session has written anything yet, so both
            # independently see a title with nothing pending — the ordinary shape of a
            # double-click on a slow connection.
            assert await repository_a.has_pending_for_title(title_id) is False
            assert await repository_b.has_pending_for_title(title_id) is False

            repository_a.add(
                CollectionBackfill(
                    title_id=title_id,
                    requested_from=requested_from,
                    requested_until=requested_until,
                    status=CollectionBackfillStatus.QUEUED,
                    page_cap=5,
                )
            )
            repository_b.add(
                CollectionBackfill(
                    title_id=title_id,
                    requested_from=requested_from,
                    requested_until=requested_until,
                    status=CollectionBackfillStatus.QUEUED,
                    page_cap=5,
                )
            )

            await session_a.commit()
            with pytest.raises(IntegrityError):
                await session_b.commit()
            await session_b.rollback()
        finally:
            await session_a.close()
            await session_b.close()
    finally:
        await engine.dispose()

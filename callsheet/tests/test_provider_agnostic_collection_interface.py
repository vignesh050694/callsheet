"""Tests for E03-S07 — Swap a data provider behind a stable interface, so one vendor
can't take the product down.

Story: stories/E03-agentic-collection-layer/E03-S07-provider-agnostic-collection-interface.md
Epic: stories/E03-agentic-collection-layer/EPIC.md

The story has one Gherkin scenario ("An X search endpoint is deprecated and must be
replaced"). Its Given/When/Then clauses, plus the notes and the task brief's own list of
what a real corpus must survive, map to the sections below:

  - "Given: the collection agent calls platforms through an internal interface that
    speaks in platform + query + page, not in vendor endpoint paths" -> Section 1: the
    port's signature, and proof that vendor vocabulary (tikhub's `keyword`/`cursor`,
    apify's `searchTerms`/`maxItems`) lives only inside the adapter the caller never sees.
  - "and Given: each platform has a configured primary endpoint and an optional
    alternative" -> Section 2: `PlatformEndpoints.active_key`, the default catalogue, and
    the differing price models that make a switchover a real decision (concept note §7).
  - "and Given: every provider response is normalised into a single internal mention
    shape before storage" -> Section 3: both adapters reading the captured fixtures into
    `NormalizedMention`, and agreeing on identity/text for the overlap post.
  - "and Given: raw vendor payloads are still stored verbatim alongside the normalised
    form" -> Section 4: `MentionRawPayload` holds the exact captured item, and its
    provenance (provider, endpoint_key, adapter_version) is reachable only by a join.
  - "When: I change the configured endpoint for X to the alternative provider" / "Then:
    collection continues against the new endpoint with no change to pipeline code or
    dashboards, and mentions from both providers appear in one continuous trend" ->
    Section 5: the same `CollectionService.collect_page` call, unchanged, run once
    against each config; and the corpus-level proof — the tweet the two captures share
    ends up as exactly one mention and one raw payload, not two.
  - "the internal mention shape carries no provider/endpoint/vendor field" -> Section 6.
  - "an item that cannot be normalised still has its raw payload stored, with the error
    recorded and no mention" -> Section 7.
  - "misconfiguration ... must fail loudly rather than collect nothing" -> Section 8:
    an unknown endpoint key, another platform's endpoint, an endpoint nobody mapped, a
    platform with no route at all, and a PER_RESULT endpoint asked for an unusable cap.
  - "the unconfigured transport/source refuses (503-style domain error) rather than
    returning an empty page" -> Section 9, including the actual `app/api/deps.py`
    bindings a fresh deployment gets.
  - Real-payload facts the normalisers must survive -> Section 10: tikhub's `views` as a
    string against apify's int, X's legacy timestamp format, `&amp;` unescaping, the
    derived-vs-real permalink, and hashtag case preserved across `#DCMovie`/`dcmovie`.
  - "Idempotency: collecting the same page twice must not duplicate mentions or
    payloads" -> Section 11.

Every fixture payload used below is either the captured JSON verbatim (identified by
tweet id) or, for the one deliberately-broken item in Section 7, a real captured item
with a single required field removed — never an invented payload. No test calls Monid;
`FixtureTransport` replays the two committed captures at
`tests/fixtures/collection/x_tikhub_search_timeline.json` and
`tests/fixtures/collection/x_apify_tweet_scraper.json`.

Out of scope, per the epic (automatic mid-run failover, direct platform API fallbacks)
and per this story (collection health dashboards are E03-S05, cost governance is E09):
none of the tests below assert on those.

Sections 12-14 were added after an adversarial review round (`changes-requested`) found
three gaps:

  - Section 12 — `CollectionService` flushed but never committed, so a real deployment's
    collection run wrote nothing durable. The shared `db_session`/`api_client` fixtures
    hand every call in a test the SAME open session, so a read-after-write inside one of
    those tests always succeeds regardless of whether anything was ever committed —
    the harness itself could not have caught this. The regression test here uses its own
    file-backed SQLite database and two independent sessions instead.
  - Section 13 — an unreadable item's external id was read from `item.mention`, which is
    None exactly when the item is unreadable, so it bypassed dedup and was re-inserted on
    every overlapping poll forever. Fixed by reading the id independently
    (`EndpointAdapter.read_external_id`); covered here across repeated polls, including
    the honest remainder — an item with no readable id at all still cannot be
    deduplicated, and that case logs `collection.normalize.unidentifiable` at error.
  - Section 14 — `longest_text` (the function that exists because one real apify capture
    had `text` holding the full post while `fullText` was truncated) was never exercised
    on input where the two fields actually diverge; both fixture files happen to have
    `text == fullText` in every item. Covered with synthetic input, labelled as such.
"""

import inspect
import json
import logging
import uuid
from dataclasses import fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_collection_source, get_monid_transport
from app.core.collection_endpoints import PriceModel, get_endpoint
from app.core.config import PlatformEndpoints, Settings
from app.core.exceptions import ServiceUnavailableError
from app.core.platforms import Platform
from app.models import Base
from app.models.mention import Mention, MentionRawPayload
from app.models.organization import Organization, OrganizationType
from app.models.title import Title
from app.repositories.mention_repository import MentionRepository
from app.services.collection.adapters.base import ProviderRequest
from app.services.collection.adapters.x_apify import ApifyXTweetScraperAdapter
from app.services.collection.adapters.x_tikhub import TikhubXSearchAdapter
from app.services.collection.mention_shape import NormalizedMention
from app.services.collection.monid_source import (
    UNCAPPED_PER_RESULT_MESSAGE,
    MonidCollectionSource,
    MonidTransport,
    UnconfiguredMonidTransport,
)
from app.services.collection.payload_values import PayloadShapeError, longest_text
from app.services.collection.routing import (
    NO_ADAPTER_MESSAGE,
    NO_ROUTE_MESSAGE,
    UNKNOWN_ENDPOINT_MESSAGE,
    WRONG_PLATFORM_MESSAGE,
    resolve_route,
)
from app.services.collection.source import (
    COLLECTION_UNAVAILABLE_MESSAGE,
    CollectionSource,
    UnconfiguredCollectionSource,
)
from app.services.collection_service import CollectionService

# ---------------------------------------------------------------------------
# Fixtures: the two committed captures, loaded once. "response" is the vendor body
# exactly as returned; "_capture" is provenance about the live run, not payload.
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "collection"


def _load_capture(filename: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / filename).read_text())


_TIKHUB_CAPTURE = _load_capture("x_tikhub_search_timeline.json")
_APIFY_CAPTURE = _load_capture("x_apify_tweet_scraper.json")

TIKHUB_RESPONSE: dict[str, Any] = _TIKHUB_CAPTURE["response"]
APIFY_RESPONSE: list[dict[str, Any]] = _APIFY_CAPTURE["response"]
TIKHUB_ITEMS: list[dict[str, Any]] = TIKHUB_RESPONSE["timeline"]

# The captures overlap on this tweet — the heart of the story's Then clause.
OVERLAP_TWEET_ID = "2087233047506866356"
QUERY = "Lokesh Kanagaraj DC"

assert len(TIKHUB_ITEMS) == 20
assert len(APIFY_RESPONSE) == 4


def _tikhub_item(tweet_id: str) -> dict[str, Any]:
    return next(item for item in TIKHUB_ITEMS if item["tweet_id"] == tweet_id)


def _apify_item(tweet_id: str) -> dict[str, Any]:
    return next(item for item in APIFY_RESPONSE if item["id"] == tweet_id)


# ---------------------------------------------------------------------------
# Test doubles and settings helpers
# ---------------------------------------------------------------------------


class FixtureTransport(MonidTransport):
    """Replays a committed capture instead of calling Monid — spends nothing.

    Records every call (endpoint key, request) so a test can assert what the adapter
    actually asked for, the way `FakeSearch` does for the preview search port.
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, ProviderRequest]] = []

    async def run(self, endpoint: Any, request: ProviderRequest) -> Any:
        self.calls.append((endpoint.key, request))
        if endpoint.key not in self._responses:
            raise AssertionError(f"FixtureTransport has no response wired for {endpoint.key!r}")
        return self._responses[endpoint.key]


def _x_settings(
    *,
    active: str = "primary",
    primary: str = "x.tikhub_search_timeline",
    alternative: str | None = "x.apify_tweet_scraper",
) -> Settings:
    """A `Settings` instance with only X's routing configured, for direct construction
    rather than mutating the process-wide cached `get_settings()`."""
    return Settings(
        collection_endpoints={
            Platform.X: PlatformEndpoints(primary=primary, alternative=alternative, active=active)
        }
    )


def _dual_provider_transport() -> FixtureTransport:
    return FixtureTransport(
        {
            "x.tikhub_search_timeline": TIKHUB_RESPONSE,
            "x.apify_tweet_scraper": APIFY_RESPONSE,
        }
    )


async def _collect(
    db_session: AsyncSession,
    transport: MonidTransport,
    settings: Settings,
    title_id: uuid.UUID,
    *,
    limit: int,
) -> Any:
    """One call through the port: platform, query, page, limit — nothing vendor-shaped.
    Used for both the primary and the alternative endpoint, unchanged, in Section 5."""
    source = MonidCollectionSource(transport, settings)
    service = CollectionService(db_session, source)
    return await service.collect_page(title_id, Platform.X, QUERY, limit=limit)


async def _run_switchover(db_session: AsyncSession, title_id: uuid.UUID) -> tuple[Any, Any]:
    """Collects the tikhub page (primary), then switches X to apify (alternative)."""
    transport = _dual_provider_transport()
    primary_result = await _collect(
        db_session, transport, _x_settings(active="primary"), title_id, limit=20
    )
    alternative_result = await _collect(
        db_session, transport, _x_settings(active="alternative"), title_id, limit=4
    )
    return primary_result, alternative_result


# ---------------------------------------------------------------------------
# Title fixture: a real title, created through the API the way any other test does,
# so the mentions collected against it live behind normal FK constraints.
# ---------------------------------------------------------------------------

ORGANIZATIONS_URL = "/api/v1/organizations"
SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}


def _titles_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/titles"


async def _create_organization(client: AsyncClient) -> str:
    response = await client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_title(client: AsyncClient, organization_id: str) -> str:
    payload = {
        "name": "DC",
        "release_date": "2026-08-15",
        "aliases": [],
        "hashtags": ["#DC"],
        "lead_cast": ["Vikram"],
        "directors": ["Lokesh Kanagaraj"],
        "music_directors": [],
        "exclusions": [],
    }
    response = await client.post(_titles_url(organization_id), json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
async def title_id(api_client: AsyncClient) -> uuid.UUID:
    organization_id = await _create_organization(api_client)
    raw_id = await _create_title(api_client, organization_id)
    return uuid.UUID(raw_id)


# ---------------------------------------------------------------------------
# Section 1 — Given: the collection agent calls platforms through an internal
# interface that speaks platform + query + page, not vendor endpoint paths.
# ---------------------------------------------------------------------------


def test_collection_source_port_speaks_platform_query_page_and_limit_only() -> None:
    signature = inspect.signature(CollectionSource.fetch)
    assert list(signature.parameters) == ["self", "platform", "query", "page", "limit"]


async def test_monid_source_fetch_reads_a_full_tikhub_page_into_normalized_mentions() -> None:
    transport = FixtureTransport({"x.tikhub_search_timeline": TIKHUB_RESPONSE})
    source = MonidCollectionSource(transport, _x_settings(active="primary"))

    page = await source.fetch(Platform.X, QUERY, limit=20)

    assert page.platform == Platform.X
    assert page.endpoint.key == "x.tikhub_search_timeline"
    assert page.adapter_version == "2026-08-11"
    assert len(page.items) == 20
    assert len(page.readable_items) == 20
    assert all(isinstance(item.mention, NormalizedMention) for item in page.items)
    assert page.next_page == TIKHUB_RESPONSE["next_cursor"]


async def test_monid_source_fetch_reads_the_apify_page_which_offers_no_next_page() -> None:
    transport = FixtureTransport({"x.apify_tweet_scraper": APIFY_RESPONSE})
    source = MonidCollectionSource(transport, _x_settings(active="alternative"))

    page = await source.fetch(Platform.X, QUERY, limit=4)

    assert page.endpoint.key == "x.apify_tweet_scraper"
    assert len(page.items) == 4
    assert page.next_page is None


async def test_vendor_vocabulary_in_the_outbound_call_is_built_by_the_adapter_not_the_caller() -> (
    None
):
    """The caller asks both endpoints for the same platform + query, unchanged. What
    actually goes out over the wire is entirely different per endpoint — proof that
    tikhub's `keyword`/`cursor` and apify's `searchTerms`/`maxItems` never had to be
    known above the adapter."""
    transport = _dual_provider_transport()

    await MonidCollectionSource(transport, _x_settings(active="primary")).fetch(
        Platform.X, QUERY, limit=20
    )
    await MonidCollectionSource(transport, _x_settings(active="alternative")).fetch(
        Platform.X, QUERY, limit=4
    )

    tikhub_key, tikhub_request = transport.calls[0]
    apify_key, apify_request = transport.calls[1]
    assert tikhub_key == "x.tikhub_search_timeline"
    assert tikhub_request.query_params == {"keyword": QUERY, "search_type": "Latest"}
    assert apify_key == "x.apify_tweet_scraper"
    assert apify_request.body == {"searchTerms": [QUERY], "maxItems": 4, "sort": "Latest"}


# ---------------------------------------------------------------------------
# Section 2 — Given: each platform has a configured primary endpoint and an optional
# alternative, and the two may charge differently (concept note §7 rules 2 and 3).
# ---------------------------------------------------------------------------


def test_default_settings_configure_a_valid_primary_endpoint_for_every_platform() -> None:
    settings = Settings()
    for platform in Platform:
        configured = settings.collection_endpoints.get(platform)
        assert configured is not None, platform
        primary_endpoint = get_endpoint(configured.primary)
        assert primary_endpoint is not None
        assert primary_endpoint.platform is platform


def test_default_settings_configure_a_valid_alternative_endpoint_for_every_platform() -> None:
    settings = Settings()
    for platform in Platform:
        configured = settings.collection_endpoints[platform]
        assert configured.alternative is not None
        alternative_endpoint = get_endpoint(configured.alternative)
        assert alternative_endpoint is not None
        assert alternative_endpoint.platform is platform
        # Primary and alternative come from different vendors — that is what makes the
        # substitution meaningful rather than cosmetic.
        primary_endpoint = get_endpoint(configured.primary)
        assert primary_endpoint.provider != alternative_endpoint.provider


def test_platform_endpoints_active_key_defaults_to_primary() -> None:
    endpoints = PlatformEndpoints(
        primary="x.tikhub_search_timeline", alternative="x.apify_tweet_scraper"
    )
    assert endpoints.active == "primary"
    assert endpoints.active_key == "x.tikhub_search_timeline"


def test_platform_endpoints_active_key_switches_to_alternative() -> None:
    endpoints = PlatformEndpoints(
        primary="x.tikhub_search_timeline",
        alternative="x.apify_tweet_scraper",
        active="alternative",
    )
    assert endpoints.active_key == "x.apify_tweet_scraper"


def test_platform_endpoints_with_no_alternative_configured_has_no_active_key_when_switched() -> (
    None
):
    """Pointing `active` at "alternative" is only a real switchover once an alternative
    has actually been vetted for the platform — this is the state before that."""
    endpoints = PlatformEndpoints(primary="x.tikhub_search_timeline", active="alternative")
    assert endpoints.active_key is None


def test_x_primary_and_alternative_differ_in_price_model_not_only_in_provider() -> None:
    """The switchover changes the *shape* of the bill, not just who is billing:
    primary is PER_CALL, alternative is PER_RESULT."""
    primary_endpoint = get_endpoint("x.tikhub_search_timeline")
    alternative_endpoint = get_endpoint("x.apify_tweet_scraper")
    assert primary_endpoint.price_model is PriceModel.PER_CALL
    assert primary_endpoint.requires_result_cap is False
    assert alternative_endpoint.price_model is PriceModel.PER_RESULT
    assert alternative_endpoint.requires_result_cap is True


# ---------------------------------------------------------------------------
# Section 3 — Given: every provider response is normalised into a single internal
# mention shape before storage.
# ---------------------------------------------------------------------------


def test_tikhub_adapter_normalizes_the_overlap_tweet() -> None:
    mention = TikhubXSearchAdapter().to_mention(_tikhub_item(OVERLAP_TWEET_ID))

    assert isinstance(mention, NormalizedMention)
    assert mention.platform == Platform.X
    assert mention.external_id == OVERLAP_TWEET_ID
    assert mention.author_handle == "TheTFICut"
    assert mention.author_display_name == "The Final Cut"


def test_apify_adapter_normalizes_the_same_overlap_tweet() -> None:
    mention = ApifyXTweetScraperAdapter().to_mention(_apify_item(OVERLAP_TWEET_ID))

    assert isinstance(mention, NormalizedMention)
    assert mention.platform == Platform.X
    assert mention.external_id == OVERLAP_TWEET_ID
    assert mention.author_handle == "TheTFICut"


def test_both_adapters_agree_on_identity_and_text_for_the_overlap_tweet() -> None:
    """The two providers, captured minutes apart against the same query, must produce
    the same post — same id, same author, same text — through their respective
    adapters. Only engagement, a collection-time snapshot, is allowed to differ."""
    tikhub_mention = TikhubXSearchAdapter().to_mention(_tikhub_item(OVERLAP_TWEET_ID))
    apify_mention = ApifyXTweetScraperAdapter().to_mention(_apify_item(OVERLAP_TWEET_ID))

    assert tikhub_mention.external_id == apify_mention.external_id
    assert tikhub_mention.author_handle == apify_mention.author_handle
    assert tikhub_mention.text == apify_mention.text
    assert tikhub_mention.platform == apify_mention.platform


# ---------------------------------------------------------------------------
# Section 4 — Given: raw vendor payloads are still stored verbatim alongside the
# normalised form, with provenance the mention itself refuses to carry.
# ---------------------------------------------------------------------------


async def test_collect_page_stores_the_raw_tikhub_payload_verbatim(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    transport = FixtureTransport({"x.tikhub_search_timeline": TIKHUB_RESPONSE})
    await _collect(db_session, transport, _x_settings(active="primary"), title_id, limit=20)

    row = (
        await db_session.execute(
            select(MentionRawPayload).where(
                MentionRawPayload.title_id == title_id,
                MentionRawPayload.external_id == OVERLAP_TWEET_ID,
            )
        )
    ).scalar_one()

    assert row.payload == _tikhub_item(OVERLAP_TWEET_ID)
    assert row.provider == "tikhub"
    assert row.endpoint_key == "x.tikhub_search_timeline"
    assert row.adapter_version == "2026-08-11"
    assert row.mention_id is not None


async def test_collect_page_stores_the_raw_apify_payload_verbatim(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    transport = FixtureTransport({"x.apify_tweet_scraper": APIFY_RESPONSE})
    await _collect(db_session, transport, _x_settings(active="alternative"), title_id, limit=4)

    row = (
        await db_session.execute(
            select(MentionRawPayload).where(
                MentionRawPayload.title_id == title_id,
                MentionRawPayload.external_id == OVERLAP_TWEET_ID,
            )
        )
    ).scalar_one()

    assert row.payload == _apify_item(OVERLAP_TWEET_ID)
    assert row.provider == "apify"
    assert row.endpoint_key == "x.apify_tweet_scraper"


async def test_provenance_is_reachable_from_a_mention_only_by_joining_its_raw_payload(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    transport = FixtureTransport({"x.tikhub_search_timeline": TIKHUB_RESPONSE})
    await _collect(db_session, transport, _x_settings(active="primary"), title_id, limit=20)

    mention = (
        await db_session.execute(
            select(Mention).where(
                Mention.title_id == title_id, Mention.external_id == OVERLAP_TWEET_ID
            )
        )
    ).scalar_one()

    payload = await MentionRepository(db_session).get_payload_for_mention(mention.id)
    assert payload is not None
    assert payload.provider == "tikhub"
    assert payload.endpoint_key == "x.tikhub_search_timeline"


# ---------------------------------------------------------------------------
# Section 5 — When/Then: change X's configured endpoint to the alternative provider.
# Collection continues through the unchanged pipeline call, and mentions from both
# providers land in one continuous trend with no duplicate for the overlapping post.
# ---------------------------------------------------------------------------


async def test_switching_x_from_primary_to_alternative_is_a_configuration_only_change(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    """`_collect` — one function, one call shape — is used for both endpoints below.
    Nothing about the call branches on which provider is live; only the resolved
    endpoint and provider on the result differ."""
    transport = _dual_provider_transport()

    primary_result = await _collect(
        db_session, transport, _x_settings(active="primary"), title_id, limit=20
    )
    alternative_result = await _collect(
        db_session, transport, _x_settings(active="alternative"), title_id, limit=4
    )

    assert primary_result.platform == alternative_result.platform == Platform.X
    assert primary_result.endpoint_key == "x.tikhub_search_timeline"
    assert alternative_result.endpoint_key == "x.apify_tweet_scraper"
    assert primary_result.provider == "tikhub"
    assert alternative_result.provider == "apify"


async def test_mentions_from_both_providers_after_a_switchover_form_one_continuous_series(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    primary_result, alternative_result = await _run_switchover(db_session, title_id)

    assert primary_result.stored == 20
    assert primary_result.already_known == 0
    # apify returned 4 items; one is the tweet already stored via tikhub.
    assert alternative_result.stored == 3
    assert alternative_result.already_known == 1

    mentions = await MentionRepository(db_session).list_for_title(title_id, limit=100)
    external_ids = [mention.external_id for mention in mentions]
    assert len(external_ids) == len(set(external_ids)) == 23
    assert external_ids.count(OVERLAP_TWEET_ID) == 1


async def test_overlap_post_keeps_its_first_collected_engagement_snapshot_not_the_second(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    """tikhub (collected first) saw 87 views on the overlap tweet; apify (collected
    minutes later, and second in this test) saw 93. First capture wins, which is the
    same snapshot-at-collection rule the rest of the pipeline follows — it is not a
    mismatch to be reconciled."""
    await _run_switchover(db_session, title_id)

    mentions = await MentionRepository(db_session).list_for_title(title_id, limit=100)
    overlap_mention = next(m for m in mentions if m.external_id == OVERLAP_TWEET_ID)
    assert overlap_mention.view_count == 87


async def test_the_overlap_posts_raw_payload_is_stored_once_not_once_per_provider(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    await _run_switchover(db_session, title_id)

    rows = (
        (
            await db_session.execute(
                select(MentionRawPayload).where(
                    MentionRawPayload.title_id == title_id,
                    MentionRawPayload.external_id == OVERLAP_TWEET_ID,
                )
            )
        )
        .scalars()
        .all()
    )

    assert len(rows) == 1
    assert rows[0].provider == "tikhub"


# ---------------------------------------------------------------------------
# Section 6 — Given: the internal mention shape carries no provider/endpoint/vendor
# field. A mention must not be able to say who fetched it.
# ---------------------------------------------------------------------------

_FORBIDDEN_PROVENANCE_NAMES = {
    "provider",
    "endpoint",
    "endpoint_key",
    "vendor",
    "adapter",
    "adapter_version",
    "source",
}


def test_normalized_mention_dataclass_carries_no_provider_endpoint_or_vendor_field() -> None:
    field_names = {field.name for field in fields(NormalizedMention)}
    assert field_names.isdisjoint(_FORBIDDEN_PROVENANCE_NAMES)


def test_mention_orm_model_carries_no_provider_endpoint_or_vendor_column() -> None:
    column_names = {column.name for column in Mention.__table__.columns}
    assert column_names.isdisjoint(_FORBIDDEN_PROVENANCE_NAMES)


async def test_stored_mention_rows_read_back_with_no_provider_column_regardless_of_origin(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    """Belt and suspenders on top of the schema check: mentions collected from both
    providers, read back through the repository, expose no attribute a caller could
    group or split a trend by."""
    await _run_switchover(db_session, title_id)

    mentions = await MentionRepository(db_session).list_for_title(title_id, limit=100)
    assert len(mentions) == 23
    mapper_columns = {column.key for column in Mention.__table__.columns}
    assert mapper_columns.isdisjoint(_FORBIDDEN_PROVENANCE_NAMES)


# ---------------------------------------------------------------------------
# Section 7 — An item that cannot be normalised still has its raw payload stored,
# with the error recorded and no mention.
# ---------------------------------------------------------------------------


def _tikhub_item_with_id_removed() -> dict[str, Any]:
    """A real captured item (the overlap tweet), corrupted the one way this section
    asks for: its required id field removed. Everything else is the genuine capture."""
    broken = dict(_tikhub_item(OVERLAP_TWEET_ID))
    del broken["tweet_id"]
    return broken


def test_adapter_raises_payload_shape_error_when_the_required_id_is_missing() -> None:
    with pytest.raises(PayloadShapeError):
        TikhubXSearchAdapter().to_mention(_tikhub_item_with_id_removed())


async def test_collect_page_stores_the_raw_payload_and_error_for_an_unreadable_item(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    broken_item = _tikhub_item_with_id_removed()
    response = {"status": "ok", "timeline": [broken_item], "next_cursor": None}
    transport = FixtureTransport({"x.tikhub_search_timeline": response})

    result = await _collect(
        db_session, transport, _x_settings(active="primary"), title_id, limit=20
    )

    assert result.stored == 0
    assert result.unreadable == 1

    mentions = (await db_session.execute(select(Mention))).scalars().all()
    assert mentions == []

    payloads = (await db_session.execute(select(MentionRawPayload))).scalars().all()
    assert len(payloads) == 1
    stored_payload = payloads[0]
    assert stored_payload.mention_id is None
    assert stored_payload.external_id is None
    assert stored_payload.normalization_error is not None
    assert "tweet_id" in stored_payload.normalization_error
    # The rest of the paid-for item is kept exactly as it arrived.
    assert stored_payload.payload == broken_item


# ---------------------------------------------------------------------------
# Section 8 — Misconfiguration must fail loudly rather than collect nothing: an
# unknown endpoint key, another platform's endpoint, an endpoint with no adapter, a
# platform with no route at all, and a PER_RESULT endpoint with an unusable cap.
# ---------------------------------------------------------------------------


def test_resolve_route_refuses_an_unknown_endpoint_key() -> None:
    settings = _x_settings(primary="x.nonexistent_endpoint", alternative=None)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        resolve_route(Platform.X, settings)

    assert str(exc_info.value) == UNKNOWN_ENDPOINT_MESSAGE.format(key="x.nonexistent_endpoint")


def test_resolve_route_refuses_an_endpoint_that_belongs_to_a_different_platform() -> None:
    """A key that resolves but names another platform's endpoint is the mistake worth
    catching hardest — left unchecked it would collect real posts about the wrong
    platform's conversation while looking configured."""
    settings = _x_settings(primary="reddit.tikhub_dynamic_search", alternative=None)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        resolve_route(Platform.X, settings)

    assert str(exc_info.value) == WRONG_PLATFORM_MESSAGE.format(
        key="reddit.tikhub_dynamic_search", actual=Platform.REDDIT, expected=Platform.X
    )


def test_resolve_route_refuses_an_endpoint_with_no_adapter_mapped_yet() -> None:
    """Instagram, Reddit, and YouTube are routed in the default configuration but have
    no adapter yet (only X ships one in this story) — collecting through them would
    silently store nothing, so routing refuses instead."""
    settings = Settings()

    for platform, endpoint_key in (
        (Platform.INSTAGRAM, "instagram.tikhub_hashtag_search"),
        (Platform.REDDIT, "reddit.tikhub_dynamic_search"),
        (Platform.YOUTUBE, "youtube.tikhub_video_comments"),
    ):
        with pytest.raises(ServiceUnavailableError) as exc_info:
            resolve_route(platform, settings)
        assert str(exc_info.value) == NO_ADAPTER_MESSAGE.format(
            key=endpoint_key, platform=platform
        )


def test_resolve_route_refuses_a_platform_with_no_configured_endpoints_at_all() -> None:
    settings = Settings(collection_endpoints={})

    with pytest.raises(ServiceUnavailableError) as exc_info:
        resolve_route(Platform.X, settings)

    assert str(exc_info.value) == NO_ROUTE_MESSAGE.format(platform=Platform.X)


def test_resolve_route_refuses_switching_active_to_an_alternative_that_was_never_configured() -> (
    None
):
    """The switchover scenario's own failure mode: flipping `active` to "alternative"
    before an alternative has been vetted for the platform must not silently fall back
    to the primary — it must refuse."""
    settings = _x_settings(alternative=None, active="alternative")

    with pytest.raises(ServiceUnavailableError) as exc_info:
        resolve_route(Platform.X, settings)

    assert str(exc_info.value) == NO_ROUTE_MESSAGE.format(platform=Platform.X)


async def test_a_misconfigured_route_fails_before_the_source_makes_any_call() -> None:
    transport = FixtureTransport({})
    source = MonidCollectionSource(transport, Settings(collection_endpoints={}))

    with pytest.raises(ServiceUnavailableError):
        await source.fetch(Platform.X, QUERY, limit=20)

    assert transport.calls == []


async def test_an_endpoint_with_no_adapter_fails_via_the_source_too_without_calling_out() -> None:
    transport = FixtureTransport({})
    source = MonidCollectionSource(transport, Settings())

    with pytest.raises(ServiceUnavailableError):
        await source.fetch(Platform.INSTAGRAM, "any query", limit=20)

    assert transport.calls == []


async def test_per_result_endpoint_refuses_an_unusable_zero_cap_without_calling_the_transport() -> (
    None
):
    """On the PER_RESULT alternative, the cap *is* the bill — a cap of 0 has no
    ceiling at all, and the port must refuse to make that call rather than letting it
    through and paying for whatever comes back."""
    transport = FixtureTransport({"x.apify_tweet_scraper": APIFY_RESPONSE})
    source = MonidCollectionSource(transport, _x_settings(active="alternative"))

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await source.fetch(Platform.X, QUERY, limit=0)

    assert str(exc_info.value) == UNCAPPED_PER_RESULT_MESSAGE.format(
        key="x.apify_tweet_scraper", limit=0
    )
    assert transport.calls == []


# ---------------------------------------------------------------------------
# Section 9 — The unconfigured transport/source refuses (503-style domain error)
# rather than returning an empty page, which would be indistinguishable from "nobody
# is talking about this title".
# ---------------------------------------------------------------------------


async def test_unconfigured_monid_transport_refuses_rather_than_returning_a_response() -> None:
    transport = UnconfiguredMonidTransport()
    endpoint = get_endpoint("x.tikhub_search_timeline")
    request = ProviderRequest(query_params={"keyword": QUERY})

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await transport.run(endpoint, request)

    assert str(exc_info.value) == COLLECTION_UNAVAILABLE_MESSAGE


async def test_unconfigured_collection_source_refuses_rather_than_returning_an_empty_page() -> (
    None
):
    source = UnconfiguredCollectionSource()

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await source.fetch(Platform.X, QUERY, limit=20)

    assert str(exc_info.value) == COLLECTION_UNAVAILABLE_MESSAGE


async def test_default_dependency_bindings_compose_to_the_same_unconfigured_refusal() -> None:
    """`app/api/deps.py`'s `get_monid_transport`/`get_collection_source` are exactly
    what a deployment with no Monid credential gets (E03-S01). Composed together they must
    refuse the same way the standalone pieces do.

    `Settings()` here is the suite's own environment, which `is_collection_configured`
    treats as unconfigured whatever key happens to sit in a developer's `.env` — so this
    exercises the refusing path rather than spending money to prove it refuses."""
    settings = Settings()
    transport = get_monid_transport(settings)
    assert isinstance(transport, UnconfiguredMonidTransport)

    source = get_collection_source(transport, settings)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await source.fetch(Platform.X, QUERY, limit=20)
    assert str(exc_info.value) == COLLECTION_UNAVAILABLE_MESSAGE


# ---------------------------------------------------------------------------
# Section 10 — Real-payload facts the normalisers must survive, drawn from the
# captures themselves rather than from the vendors' documentation.
# ---------------------------------------------------------------------------


def test_tikhub_views_arrives_as_a_string_and_is_coerced_to_an_int() -> None:
    item = _tikhub_item(OVERLAP_TWEET_ID)
    assert isinstance(item["views"], str)  # the captured fact itself

    mention = TikhubXSearchAdapter().to_mention(item)

    assert mention.engagement.view_count == 87
    assert isinstance(mention.engagement.view_count, int)


def test_apify_view_count_arrives_as_an_int_directly() -> None:
    item = _apify_item(OVERLAP_TWEET_ID)
    assert isinstance(item["viewCount"], int)

    mention = ApifyXTweetScraperAdapter().to_mention(item)

    assert mention.engagement.view_count == 93


def test_x_legacy_timestamp_format_is_parsed_by_both_adapters() -> None:
    expected = datetime(2026, 8, 11, 17, 41, 52, tzinfo=UTC)
    tikhub_item = _tikhub_item(OVERLAP_TWEET_ID)
    apify_item = _apify_item(OVERLAP_TWEET_ID)
    assert tikhub_item["created_at"] == "Tue Aug 11 17:41:52 +0000 2026"
    assert apify_item["createdAt"] == "Tue Aug 11 17:41:52 +0000 2026"

    assert TikhubXSearchAdapter().to_mention(tikhub_item).posted_at == expected
    assert ApifyXTweetScraperAdapter().to_mention(apify_item).posted_at == expected


def test_ampersand_html_entity_is_unescaped_in_post_text() -> None:
    item = _apify_item("2087202312163106837")
    assert "&amp;" in item["text"]

    mention = ApifyXTweetScraperAdapter().to_mention(item)

    assert "&amp;" not in mention.text
    assert "Lokesh Kanagaraj & Arun Matheswaran" in mention.text


def test_tikhub_has_no_permalink_so_one_is_derived_from_handle_and_id() -> None:
    item = _tikhub_item(OVERLAP_TWEET_ID)
    assert "url" not in item
    assert "permalink" not in item

    mention = TikhubXSearchAdapter().to_mention(item)

    assert mention.permalink == f"https://x.com/TheTFICut/status/{OVERLAP_TWEET_ID}"


def test_apify_returns_a_real_permalink_url_directly_instead_of_a_derived_one() -> None:
    item = _apify_item(OVERLAP_TWEET_ID)

    mention = ApifyXTweetScraperAdapter().to_mention(item)

    assert item["url"] == f"https://x.com/TheTFICut/status/{OVERLAP_TWEET_ID}"
    assert mention.permalink == item["url"]


def test_hashtag_case_is_preserved_across_mixed_and_lowercase_variants_in_one_capture() -> None:
    """`#DCMovie` and `#dcmovie` both occur in the tikhub capture. Case must survive
    normalisation untouched — folding it here would destroy evidence alias discovery
    (E02-S04) needs to rank what people actually typed."""
    mixed_case_item = _tikhub_item("2087182165117423709")
    lowercase_item = _tikhub_item("2085757990565794144")

    mixed_case_mention = TikhubXSearchAdapter().to_mention(mixed_case_item)
    lowercase_mention = TikhubXSearchAdapter().to_mention(lowercase_item)

    assert "DCMovie" in mixed_case_mention.hashtags
    assert "dcmovie" in lowercase_mention.hashtags


# ---------------------------------------------------------------------------
# Section 11 — Idempotency: collecting the same page twice must not duplicate
# mentions or payloads.
# ---------------------------------------------------------------------------


async def test_collecting_the_same_tikhub_page_twice_does_not_duplicate_mentions_or_payloads(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    transport = FixtureTransport({"x.tikhub_search_timeline": TIKHUB_RESPONSE})
    settings = _x_settings(active="primary")

    first = await _collect(db_session, transport, settings, title_id, limit=20)
    second = await _collect(db_session, transport, settings, title_id, limit=20)

    assert first.stored == 20
    assert first.already_known == 0
    assert second.stored == 0
    assert second.already_known == 20

    mention_count = len((await db_session.execute(select(Mention))).scalars().all())
    payload_count = len((await db_session.execute(select(MentionRawPayload))).scalars().all())
    assert mention_count == 20
    assert payload_count == 20


async def test_a_third_repeat_collection_still_reports_zero_new_rows(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    """Not just "twice is safe" — repeated polling of an unchanged page must stay a
    no-op indefinitely, the way a real cadence would re-poll it (E03-S02)."""
    transport = FixtureTransport({"x.apify_tweet_scraper": APIFY_RESPONSE})
    settings = _x_settings(active="alternative")

    for _ in range(3):
        result = await _collect(db_session, transport, settings, title_id, limit=4)

    assert result.stored == 0
    assert result.already_known == 4

    mention_count = len((await db_session.execute(select(Mention))).scalars().all())
    assert mention_count == 4


# ---------------------------------------------------------------------------
# Section 12 — Regression (adversarial review, finding 1): `CollectionService` must
# commit, not just flush, or a real deployment's collection run writes nothing
# durable. The shared `db_session`/`api_client` fixtures cannot catch this — every
# call in a test gets the SAME open session, so a read-after-write inside one test
# always succeeds whether or not anything was ever committed. This test uses its own
# file-backed SQLite database (an in-memory one hands out a fresh, empty database per
# connection, which would hide the bug the same way the shared fixture does) and two
# independent sessions from two independent connections, so the write is observed
# from a session that did not perform it.
# ---------------------------------------------------------------------------


async def test_collect_page_commits_so_a_second_independent_session_sees_the_write(
    tmp_path: Path,
) -> None:
    """Sensitivity was verified by hand: temporarily removing
    `await self._session.commit()` from `CollectionService.collect_page` and rerunning
    this test alone makes it fail (the reader session sees 0 mentions and 0 payloads
    instead of 20 each), because closing `writer_session` without a commit rolls back
    everything `_store` added — restoring the line makes it pass again. See the task
    report for the exact command and output."""
    db_path = tmp_path / "collection_durability.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as writer_session:
            organization = Organization(
                name="Sun Pictures",
                slug="sun-pictures-durability",
                organization_type=OrganizationType.PRODUCTION_HOUSE,
            )
            writer_session.add(organization)
            await writer_session.flush()
            title = Title(
                organization_id=organization.id, name="DC", release_date=date(2026, 8, 15)
            )
            writer_session.add(title)
            # Committing the setup rows is expected and irrelevant to what is under
            # test — the collection write below is what must survive on its own.
            await writer_session.commit()
            title_id = title.id

            transport = FixtureTransport({"x.tikhub_search_timeline": TIKHUB_RESPONSE})
            source = MonidCollectionSource(transport, _x_settings(active="primary"))
            service = CollectionService(writer_session, source)
            await service.collect_page(title_id, Platform.X, QUERY, limit=20)
            # Deliberately no explicit commit here: whether the write below is
            # observed depends entirely on whether `collect_page` committed it itself.

        async with session_factory() as reader_session:
            mentions = (
                (
                    await reader_session.execute(
                        select(Mention).where(Mention.title_id == title_id)
                    )
                )
                .scalars()
                .all()
            )
            payloads = (
                (
                    await reader_session.execute(
                        select(MentionRawPayload).where(MentionRawPayload.title_id == title_id)
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()

    assert len(mentions) == 20
    assert len(payloads) == 20


# ---------------------------------------------------------------------------
# Section 13 — Regression (adversarial review, finding 2): an unreadable item's
# external id must be read independently of `to_mention`, or it can never be
# deduplicated across overlapping polls and accumulates forever. Covers the fixed
# case (a readable id survives normalisation failure) and the honest remainder (no
# id at all still cannot be deduplicated, and that is logged loudly).
# ---------------------------------------------------------------------------


def _tikhub_item_with_screen_name_removed() -> dict[str, Any]:
    """A real captured item (the overlap tweet), corrupted the way this section asks
    for: `screen_name` removed, so it cannot become a mention, while `tweet_id` — its
    readable id — stays intact. This is what a real overlapping poll produces: an
    item the adapter cannot read, but can still recognise next time."""
    broken = dict(_tikhub_item(OVERLAP_TWEET_ID))
    del broken["screen_name"]
    return broken


async def test_unreadable_item_with_a_readable_id_leaves_one_raw_payload_across_three_polls(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    broken_item = _tikhub_item_with_screen_name_removed()
    response = {"status": "ok", "timeline": [broken_item], "next_cursor": None}
    transport = FixtureTransport({"x.tikhub_search_timeline": response})
    settings = _x_settings(active="primary")

    first = await _collect(db_session, transport, settings, title_id, limit=20)
    second = await _collect(db_session, transport, settings, title_id, limit=20)
    third = await _collect(db_session, transport, settings, title_id, limit=20)

    assert first.unreadable == 1
    assert first.stored == 0
    assert first.already_known == 0
    for repeat_result in (second, third):
        assert repeat_result.unreadable == 0
        assert repeat_result.stored == 0
        assert repeat_result.already_known == 1

    payloads = (await db_session.execute(select(MentionRawPayload))).scalars().all()
    assert len(payloads) == 1


async def test_unreadable_items_stored_payload_keeps_its_id_and_error_for_a_later_re_read(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    broken_item = _tikhub_item_with_screen_name_removed()
    response = {"status": "ok", "timeline": [broken_item], "next_cursor": None}
    transport = FixtureTransport({"x.tikhub_search_timeline": response})

    await _collect(db_session, transport, _x_settings(active="primary"), title_id, limit=20)

    stored_payload = (await db_session.execute(select(MentionRawPayload))).scalar_one()
    assert stored_payload.external_id == OVERLAP_TWEET_ID
    assert stored_payload.mention_id is None
    assert stored_payload.normalization_error is not None
    assert "screen_name" in stored_payload.normalization_error
    # The rest of the paid-for item is kept exactly as it arrived, so it can be
    # re-read once the mapping is fixed, without paying again.
    assert stored_payload.payload == broken_item


async def test_an_item_with_no_readable_id_at_all_still_cannot_be_deduplicated(
    db_session: AsyncSession, title_id: uuid.UUID
) -> None:
    """The honest remainder: unlike the `screen_name`-only case above, an item with no
    id at all has nothing to recognise it by, so it is stored again on every
    overlapping poll rather than being deduplicated."""
    broken_item = _tikhub_item_with_id_removed()
    response = {"status": "ok", "timeline": [broken_item], "next_cursor": None}
    transport = FixtureTransport({"x.tikhub_search_timeline": response})
    settings = _x_settings(active="primary")

    first = await _collect(db_session, transport, settings, title_id, limit=20)
    second = await _collect(db_session, transport, settings, title_id, limit=20)

    assert first.unreadable == 1
    assert second.unreadable == 1
    assert second.already_known == 0

    payloads = (await db_session.execute(select(MentionRawPayload))).scalars().all()
    assert len(payloads) == 2


async def test_an_item_with_no_readable_id_logs_unidentifiable_at_error(
    db_session: AsyncSession, title_id: uuid.UUID, caplog: pytest.LogCaptureFixture
) -> None:
    broken_item = _tikhub_item_with_id_removed()
    response = {"status": "ok", "timeline": [broken_item], "next_cursor": None}
    transport = FixtureTransport({"x.tikhub_search_timeline": response})
    caplog.set_level(logging.WARNING)

    await _collect(db_session, transport, _x_settings(active="primary"), title_id, limit=20)

    error_records = [
        record
        for record in caplog.records
        if record.levelname == "ERROR"
        and "collection.normalize.unidentifiable" in record.message
    ]
    assert len(error_records) == 1


# ---------------------------------------------------------------------------
# Section 14 — Regression (adversarial review, finding 3): `longest_text` exists
# because one real captured apify item had `text` holding the full post while
# `fullText` was truncated — the reverse of what the field names suggest — but that
# item was excluded from the committed fixture for size, and the 4 items that remain
# all have `text == fullText` byte-for-byte. These are synthetic inputs, built to
# exercise the divergence directly rather than relying on the fixture for it.
# ---------------------------------------------------------------------------


def test_longest_text_returns_the_first_candidate_when_it_is_the_longer_one() -> None:
    """Synthetic, mirroring the real (excluded) capture: `text` is the fuller field."""
    fuller_text_field = (
        "The full, untruncated post body — much longer than the preview below."
    )
    truncated_full_text_field = "Truncated preview... https://t.co/abc123"
    assert len(fuller_text_field) > len(truncated_full_text_field)

    assert longest_text(fuller_text_field, truncated_full_text_field) == fuller_text_field


def test_longest_text_returns_the_second_candidate_when_it_is_the_longer_one() -> None:
    """Synthetic: the more intuitive shape, where `fullText` genuinely is fuller.
    `longest_text` has no preference for either field name — length alone decides."""
    truncated_text_field = "Short preview"
    fuller_full_text_field = (
        "This is the fuller field, carrying the whole post body, untruncated."
    )
    assert len(fuller_full_text_field) > len(truncated_text_field)

    assert longest_text(truncated_text_field, fuller_full_text_field) == fuller_full_text_field


def test_longest_text_uses_whichever_single_candidate_is_present_when_the_other_is_none() -> (
    None
):
    assert longest_text(None, "only this one is present") == "only this one is present"
    assert longest_text("only this one is present", None) == "only this one is present"


def test_longest_text_raises_payload_shape_error_when_both_candidates_are_missing() -> None:
    with pytest.raises(PayloadShapeError):
        longest_text(None, None)

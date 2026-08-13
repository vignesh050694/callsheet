"""Tests for E03-S04 — Reprocess the whole corpus with a better model without paying to
collect it again.

Story: stories/E03-agentic-collection-layer/E03-S04-raw-payload-store-and-reprocess.md
Epic: stories/E03-agentic-collection-layer/EPIC.md

The story has one Gherkin scenario. Its Given/When/Then clauses, plus the task brief's own
list of what must be covered, map to the sections below:

  - "and Given: every collection response was stored verbatim" -> exercised by building
    every corpus in these tests through the real `CollectionService` + committed fixture
    captures, never through hand-built payloads (Section 0 helpers).
  - "and Given: derived fields ... are stored separately from the raw payload and are
    versioned by pipeline version" -> Section 2 (additive reprocessing under a new
    version) and the `MentionAnalysis` table itself (a separate table, keyed
    `(mention_id, pipeline_version)`).
  - "and Given: a reprocess job can target a title and a date range" -> Section 3.
  - "Then: all derived fields are recomputed from stored payloads with zero collection
    spend" -> Section 1 (spend is asserted structurally: no `CollectionSource` /
    transport is reachable from `ReprocessService`, not merely a zero counter) and
    Section 11 (durability of that recompute).
  - "and the dashboard reflects the new results with its pipeline version recorded" ->
    Section 2 and Section 11 (a second, independent session/connection can read the new
    rows).

Additional coverage the task brief calls out by name:
  - Section 4 — same-version reruns are idempotent.
  - Section 5 — the `_remap` path and its four-way `_RemapOutcome`: repair from
    payload (`UPDATED`), no-op on an already-correct mention (`UNCHANGED`), a payload
    still unreadable under the current mapping (`UNREADABLE`, left completely
    untouched), an endpoint with no adapter registered (`UNVERIFIABLE`), and one run
    reporting a mix of all four at once.
  - Section 6 — the SQLite naive-vs-aware datetime trap `_differs`/`_as_utc` exist for.
  - Section 7 — the unconfigured analyzer refuses rather than writing neutral verdicts.
  - Section 8 — an analyzer returning fewer verdicts than requested leaves the rest
    unjudged, resumable by a later run.
  - Section 9 — a title that does not exist is refused.
  - Section 10 — batching: `REPROCESS_BATCH_SIZE` is 200, and the keyset-paged walk
    covers a corpus spanning multiple batches without skipping or repeating.
  - Section 11 — durability, using the file-backed/two-session pattern the task brief
    requires: the shared `db_session` fixture hands every call in a test the SAME open
    session, which would mask a missing `session.commit()` in `reprocess_title` the same
    way it masked the E03-S07 regression documented in
    `test_provider_agnostic_collection_interface.py`.

Coverage added after the first adversarial review round (`changes-requested`, five
findings, all real — the implementation was fixed, not the tests):

  - Section 10 (extended) — Finding 1, the most valuable coverage in the story: the
    corpus walk pages by `Mention.id` rather than `posted_at` precisely because
    `_remap` can rewrite `posted_at` mid-walk (correcting a timestamp is what a
    reprocess exists to do), and paging by a column the walk itself mutates skips or
    repeats rows. Two tests combine batching *and* remapping — deliberately, since the
    existing multi-batch test builds payload-less mentions where `_remap` never runs —
    shifting one mention's `posted_at` forward past the rest of the corpus, and
    backward before it, and proving `examined` lands on the corpus size exactly either
    way.
  - Section 12 — Finding 4: `reprocess_title` commits per batch rather than once at
    the end, so a run that fails partway through leaves the completed batches durably
    committed, and a later run resumes rather than redoing them.
  - Section 13 — Finding 3: `scripts/reprocess_title.py`'s own logic — `_parse_day`
    and `_build_parser` — tested directly, never by running the script against a real
    database.
  - Section 14 — Finding 5: `MentionAnalysisRepository.delete_for_title_and_version`,
    "the undo for a bad model run," had no coverage at all.

No test calls Monid. `FixtureTransport` replays the two committed captures at
`tests/fixtures/collection/x_tikhub_search_timeline.json` (20 real posts) and
`x_apify_tweet_scraper.json` (4 real posts) — the same fixtures and replay approach
`test_provider_agnostic_collection_interface.py` uses. Every corpus in these tests is
built by actually running it through `CollectionService`, never by hand-constructing
`Mention`/`MentionRawPayload` rows, except where a test is explicitly about the keyset
walk's mechanics (Section 10), which needs a corpus larger than one batch and does not
depend on payload content.
"""

import argparse
import inspect
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.reprocess_service as reprocess_service_module
from app.api.deps import get_reprocess_service
from app.core.config import PlatformEndpoints, Settings
from app.core.exceptions import (
    ResourceNotFoundError,
    ServiceUnavailableError,
    ValidationFailedError,
)
from app.core.platforms import Platform

# Moved to `app.core.timestamps` in E03-S01, where the rule about reading stored
# timestamps is findable by the next caller who needs it. Aliased rather than renamed
# throughout, so what this section asserts stays word for word what it asserted when the
# defect it covers was found.
from app.core.timestamps import as_utc as _as_utc
from app.models import Base
from app.models.mention import Mention, MentionRawPayload
from app.models.mention_analysis import MentionAnalysis
from app.models.organization import Organization, OrganizationType
from app.models.title import Title
from app.repositories.mention_analysis_repository import MentionAnalysisRepository
from app.repositories.mention_repository import MentionRepository
from app.services.analysis.mention_analyzer import (
    ANALYSIS_UNAVAILABLE_MESSAGE,
    AnalysisVerdict,
    AnalyzableMention,
    MentionAnalyzer,
    UnconfiguredMentionAnalyzer,
)
from app.services.collection.adapters.base import ProviderRequest
from app.services.collection.mention_shape import NormalizedMention
from app.services.collection.monid_source import MonidCollectionSource, MonidTransport
from app.services.collection_service import CollectionService
from app.services.reprocess_service import (
    INVALID_WINDOW_MESSAGE,
    REPROCESS_BATCH_SIZE,
    TITLE_NOT_FOUND_MESSAGE,
    ReprocessService,
    _differs,
    _RemapOutcome,
)
from scripts.reprocess_title import _build_parser, _parse_day

# ---------------------------------------------------------------------------
# Section 0 — Fixtures and helpers. The corpus these tests reprocess is always built by
# running the committed captures through the real `CollectionService`, the same replay
# approach `test_provider_agnostic_collection_interface.py` uses.
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "collection"


def _load_capture(filename: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / filename).read_text())


_TIKHUB_CAPTURE = _load_capture("x_tikhub_search_timeline.json")
_APIFY_CAPTURE = _load_capture("x_apify_tweet_scraper.json")

TIKHUB_RESPONSE: dict[str, Any] = _TIKHUB_CAPTURE["response"]
APIFY_RESPONSE: list[dict[str, Any]] = _APIFY_CAPTURE["response"]
TIKHUB_ITEMS: list[dict[str, Any]] = TIKHUB_RESPONSE["timeline"]

OVERLAP_TWEET_ID = "2087233047506866356"
QUERY = "Lokesh Kanagaraj DC"

assert len(TIKHUB_ITEMS) == 20
assert len(APIFY_RESPONSE) == 4


def _tikhub_item(tweet_id: str) -> dict[str, Any]:
    return next(item for item in TIKHUB_ITEMS if item["tweet_id"] == tweet_id)


def _tikhub_item_with_screen_name_removed(tweet_id: str = OVERLAP_TWEET_ID) -> dict[str, Any]:
    """A real captured item, corrupted the one way this file needs it: its required
    handle field removed, so `to_mention` raises `PayloadShapeError` under today's
    adapter while everything else is the genuine capture."""
    broken = dict(_tikhub_item(tweet_id))
    del broken["screen_name"]
    return broken


class FixtureTransport(MonidTransport):
    """Replays a committed capture instead of calling Monid — spends nothing.

    Only ever used to build a corpus via `CollectionService` in these tests. Where a
    transport instance is constructed but deliberately never handed to
    `ReprocessService` (Section 1), it exists solely so a test can assert it was never
    reached.
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, ProviderRequest]] = []

    async def run(self, endpoint: Any, request: ProviderRequest) -> Any:
        self.calls.append((endpoint.key, request))
        if endpoint.key not in self._responses:
            raise AssertionError(f"FixtureTransport has no response wired for {endpoint.key!r}")
        return self._responses[endpoint.key]


def _x_settings(*, active: str = "primary") -> Settings:
    return Settings(
        collection_endpoints={
            Platform.X: PlatformEndpoints(
                primary="x.tikhub_search_timeline",
                alternative="x.apify_tweet_scraper",
                active=active,
            )
        }
    )


async def _create_title(
    session: AsyncSession, *, release_date: date = date(2026, 8, 15)
) -> uuid.UUID:
    organization = Organization(
        name="Sun Pictures",
        slug=f"sun-pictures-{uuid.uuid4().hex[:8]}",
        organization_type=OrganizationType.PRODUCTION_HOUSE,
    )
    session.add(organization)
    await session.flush()
    title = Title(organization_id=organization.id, name="DC", release_date=release_date)
    session.add(title)
    await session.flush()
    return title.id


async def _collect_tikhub_corpus(
    session: AsyncSession, title_id: uuid.UUID, *, limit: int = 20
) -> None:
    """Populates a title with the 20-post tikhub capture, verbatim payloads included —
    exactly what a poll run under E03-S07 leaves behind for this story to reprocess."""
    transport = FixtureTransport({"x.tikhub_search_timeline": TIKHUB_RESPONSE})
    source = MonidCollectionSource(transport, _x_settings(active="primary"))
    service = CollectionService(session, source)
    result = await service.collect_page(title_id, Platform.X, QUERY, limit=limit)
    assert result.stored == limit


async def _add_synthetic_mentions(
    session: AsyncSession, title_id: uuid.UUID, count: int
) -> list[Mention]:
    """Bare mentions with no stored payload, for testing the keyset walk's mechanics
    alone (Section 10) — that walk reads the `mentions` table and does not care what a
    payload holds."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    mentions = []
    for index in range(count):
        mention = Mention(
            title_id=title_id,
            platform=Platform.X,
            external_id=f"synthetic-{index:04d}",
            author_handle="synthetic_user",
            author_display_name="Synthetic User",
            text=f"synthetic mention {index}",
            posted_at=start + timedelta(minutes=index),
            collected_at=datetime.now(UTC),
        )
        session.add(mention)
        mentions.append(mention)
    await session.flush()
    return mentions


_SHIFTING_ENDPOINT_KEY = "test.shifting_adapter"


class _ShiftingAdapter:
    """A fake `EndpointAdapter`, monkeypatched into `get_adapter`, that reads the
    `posted_at` a test wants a mention remapped to straight out of the payload's own
    JSON. Finding 1's regression coverage needs a repair that can move `posted_at`
    anywhere — including past or before every other row in the corpus — without
    touching any production adapter."""

    version = "shifting-test-v1"

    def to_mention(self, payload: dict[str, Any]) -> NormalizedMention:
        return NormalizedMention(
            platform=Platform.X,
            external_id=payload["external_id"],
            text=payload["text"],
            posted_at=datetime.fromisoformat(payload["posted_at"]),
            author_handle=payload["author_handle"],
            author_display_name=payload["author_display_name"],
        )


async def _add_synthetic_mentions_with_payloads(
    session: AsyncSession, title_id: uuid.UUID, count: int
) -> list[Mention]:
    """Like `_add_synthetic_mentions`, but each mention also gets a real
    `MentionRawPayload` row routed at `_SHIFTING_ENDPOINT_KEY`, so `_remap` actually
    runs on it instead of short-circuiting at `payload is None`. Every field `_remap`
    compares is set explicitly (not left to a Python-side column default that only
    applies at flush) so a freshly built mention starts in exact agreement with its own
    payload — any drift a test wants has to come from deliberately editing the
    payload, never from constructor defaults."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    mentions = []
    for index in range(count):
        posted_at = start + timedelta(minutes=index)
        mention = Mention(
            title_id=title_id,
            platform=Platform.X,
            external_id=f"shift-{index:04d}",
            author_handle="synthetic_user",
            author_display_name="Synthetic User",
            text=f"synthetic mention {index}",
            posted_at=posted_at,
            permalink=None,
            author_follower_count=None,
            platform_reported_language=None,
            hashtags=[],
            collected_at=datetime.now(UTC),
        )
        session.add(mention)
        mentions.append(mention)
    await session.flush()

    for mention in mentions:
        session.add(
            MentionRawPayload(
                title_id=title_id,
                mention=mention,
                platform=Platform.X,
                external_id=mention.external_id,
                provider="synthetic",
                endpoint_key=_SHIFTING_ENDPOINT_KEY,
                adapter_version="synthetic-v0",
                payload={
                    "external_id": mention.external_id,
                    "text": mention.text,
                    "author_handle": mention.author_handle,
                    "author_display_name": mention.author_display_name,
                    # The same instant the mention already holds. A test overwrites
                    # this for whichever single mention it wants `_remap` to move.
                    "posted_at": mention.posted_at.isoformat(),
                },
                collected_at=datetime.now(UTC),
            )
        )
    await session.flush()
    return mentions


@dataclass
class FakeAnalyzer(MentionAnalyzer):
    """A configurable analyzer test double: records every batch it was asked to judge,
    and can be told to return fewer verdicts than it was asked for (Section 8)."""

    version_name: str = "pipeline-v1"
    verdict_limit: int | None = None
    calls: list[list[AnalyzableMention]] = field(default_factory=list, init=False)

    @property
    def pipeline_version(self) -> str:
        return self.version_name

    async def analyze(self, mentions: Any) -> list[AnalysisVerdict]:
        batch = list(mentions)
        self.calls.append(batch)
        verdicts = [self._verdict_for(mention) for mention in batch]
        if self.verdict_limit is not None:
            verdicts = verdicts[: self.verdict_limit]
        return verdicts

    @staticmethod
    def _verdict_for(mention: AnalyzableMention) -> AnalysisVerdict:
        return AnalysisVerdict(
            mention_id=mention.mention_id,
            detected_language="en",
            language_confidence=0.9,
            is_code_mixed=False,
            account_type="fan",
            account_type_confidence=0.8,
            sentiment_label="positive",
            sentiment_confidence=0.75,
            themes=["trailer"],
        )


@dataclass
class FailingAfterNBatchesAnalyzer(MentionAnalyzer):
    """Succeeds for its first `fail_after_batches` calls, then raises — a clean stand-in
    for "the analyzer is a network call that will fail sometimes" (Finding 4), forcing
    a `reprocess_title` run to die partway through a multi-batch corpus."""

    version_name: str
    fail_after_batches: int
    calls: list[list[AnalyzableMention]] = field(default_factory=list, init=False)

    @property
    def pipeline_version(self) -> str:
        return self.version_name

    async def analyze(self, mentions: Any) -> list[AnalysisVerdict]:
        batch = list(mentions)
        self.calls.append(batch)
        if len(self.calls) > self.fail_after_batches:
            raise RuntimeError("simulated analyzer failure mid-run")
        return [FakeAnalyzer._verdict_for(mention) for mention in batch]


async def _mention_by_external_id(
    session: AsyncSession, title_id: uuid.UUID, external_id: str
) -> Mention:
    return (
        await session.execute(
            select(Mention).where(
                Mention.title_id == title_id, Mention.external_id == external_id
            )
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# Section 1 — Then: zero collection spend, asserted structurally rather than only by a
# counter. `ReprocessService` is constructed without any `CollectionSource`/transport,
# so there is no path from it to a provider — proven both by its constructor's shape and
# by a transport that exists in the test's world but is never reached.
# ---------------------------------------------------------------------------


def test_reprocess_service_constructor_accepts_no_collection_source_or_transport() -> None:
    """Would fail if someone later handed `ReprocessService` a `CollectionSource` (or
    anything else that could reach a provider) under any parameter name."""
    signature = inspect.signature(ReprocessService.__init__)
    assert set(signature.parameters) == {"self", "session", "analyzer"}


def test_dependency_wiring_assembles_reprocess_service_without_a_collection_source() -> None:
    """The same guarantee at the FastAPI wiring layer (`app/api/deps.py`): the seam a
    real deployment uses to build `ReprocessService` cannot pass it a source either."""
    signature = inspect.signature(get_reprocess_service)
    assert set(signature.parameters) == {"session", "analyzer"}


async def test_reprocess_never_reaches_a_transport_that_exists_in_the_tests_world(
    db_session: AsyncSession,
) -> None:
    """The transport below is real and working — it could serve `x.tikhub_search_timeline`
    if asked. It is constructed here only to prove `ReprocessService` cannot reach it,
    not because it is ever handed to the service under test."""
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)

    unreachable_transport = FixtureTransport({"x.tikhub_search_timeline": TIKHUB_RESPONSE})
    analyzer = FakeAnalyzer()
    service = ReprocessService(db_session, analyzer)

    result = await service.reprocess_title(title_id)

    assert unreachable_transport.calls == []
    assert result.collection_calls == 0
    assert result.has_spent_nothing is True


# ---------------------------------------------------------------------------
# Section 2 — Given: derived fields are stored separately from the raw payload and are
# versioned by pipeline version. Reprocessing under a new version is additive: the
# previous version's rows survive unchanged, and both are readable afterwards.
# ---------------------------------------------------------------------------


async def test_reprocessing_under_a_new_pipeline_version_is_additive_not_destructive(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    repo = MentionAnalysisRepository(db_session)

    result_v1 = await ReprocessService(
        db_session, FakeAnalyzer(version_name="lang-v1")
    ).reprocess_title(title_id)
    assert result_v1.analyzed == 20

    v1_rows_before = {
        row.mention_id: (row.detected_language, row.analyzed_at, row.id)
        for row in await repo.list_for_title(title_id, "lang-v1", limit=100)
    }
    assert len(v1_rows_before) == 20

    result_v2 = await ReprocessService(
        db_session, FakeAnalyzer(version_name="lang-v2")
    ).reprocess_title(title_id)
    assert result_v2.analyzed == 20

    v1_rows_after = {
        row.mention_id: (row.detected_language, row.analyzed_at, row.id)
        for row in await repo.list_for_title(title_id, "lang-v1", limit=100)
    }
    v2_rows = await repo.list_for_title(title_id, "lang-v2", limit=100)

    assert v1_rows_after == v1_rows_before
    assert len(v2_rows) == 20

    all_rows = (await db_session.execute(select(MentionAnalysis))).scalars().all()
    assert len(all_rows) == 40
    assert set(await repo.pipeline_versions_for_title(title_id)) == {"lang-v1", "lang-v2"}


# ---------------------------------------------------------------------------
# Section 3 — Given: a reprocess job can target a title and a date range. The tikhub
# capture spans three distinct days: 2 posts on Aug 7, 6 on Aug 10, 12 on Aug 11.
# ---------------------------------------------------------------------------


async def test_reprocess_window_from_only_matches_posts_on_or_after_the_bound(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    service = ReprocessService(db_session, FakeAnalyzer())

    result = await service.reprocess_title(
        title_id, posted_from=datetime(2026, 8, 11, tzinfo=UTC)
    )

    assert result.examined == 12


async def test_reprocess_window_until_only_matches_posts_on_or_before_the_bound(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    service = ReprocessService(db_session, FakeAnalyzer())

    result = await service.reprocess_title(
        title_id, posted_until=datetime(2026, 8, 7, 23, 59, 59, tzinfo=UTC)
    )

    assert result.examined == 2


async def test_reprocess_window_with_both_bounds_matches_only_posts_inside_it(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    service = ReprocessService(db_session, FakeAnalyzer())

    result = await service.reprocess_title(
        title_id,
        posted_from=datetime(2026, 8, 10, 0, 0, 0, tzinfo=UTC),
        posted_until=datetime(2026, 8, 10, 23, 59, 59, tzinfo=UTC),
    )

    assert result.examined == 6


async def test_reprocess_window_matching_no_posts_examines_and_analyzes_nothing(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    analyzer = FakeAnalyzer()
    service = ReprocessService(db_session, analyzer)

    result = await service.reprocess_title(
        title_id,
        posted_from=datetime(2020, 1, 1, tzinfo=UTC),
        posted_until=datetime(2020, 1, 2, tzinfo=UTC),
    )

    assert result.examined == 0
    assert result.analyzed == 0
    assert result.remapped == 0
    assert result.missing_payload == 0
    assert analyzer.calls == []


async def test_reprocess_window_ending_before_it_starts_is_refused_without_touching_the_corpus(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    analyzer = FakeAnalyzer()
    service = ReprocessService(db_session, analyzer)

    with pytest.raises(ValidationFailedError) as exc_info:
        await service.reprocess_title(
            title_id,
            posted_from=datetime(2026, 8, 12, tzinfo=UTC),
            posted_until=datetime(2026, 8, 1, tzinfo=UTC),
        )

    assert str(exc_info.value) == INVALID_WINDOW_MESSAGE
    assert analyzer.calls == []
    assert (await db_session.execute(select(MentionAnalysis))).scalars().all() == []


# ---------------------------------------------------------------------------
# Section 4 — Re-running the SAME version is idempotent: no duplicate analysis rows,
# and the run reports them as already analysed.
# ---------------------------------------------------------------------------


async def test_rerunning_the_same_pipeline_version_is_idempotent(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    analyzer = FakeAnalyzer(version_name="stable-v1")
    service = ReprocessService(db_session, analyzer)

    first = await service.reprocess_title(title_id)
    second = await service.reprocess_title(title_id)

    assert first.analyzed == 20
    assert first.already_analyzed == 0
    assert second.analyzed == 0
    assert second.already_analyzed == 20

    rows = (await db_session.execute(select(MentionAnalysis))).scalars().all()
    assert len(rows) == 20


async def test_a_third_rerun_of_the_same_version_still_reports_zero_new_rows(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    analyzer = FakeAnalyzer(version_name="stable-v1")
    service = ReprocessService(db_session, analyzer)

    for _ in range(3):
        result = await service.reprocess_title(title_id)

    assert result.analyzed == 0
    assert result.already_analyzed == 20
    rows = (await db_session.execute(select(MentionAnalysis))).scalars().all()
    assert len(rows) == 20


# ---------------------------------------------------------------------------
# Section 5 — The `_remap` path and its four-way `_RemapOutcome`: a mention corrupted
# or written by a broken adapter mapping is repaired from its payload with no provider
# call (`UPDATED`); an already-correct mention is reported as remapped=0 and not
# needlessly dirtied (`UNCHANGED`); a payload still unreadable under the current
# mapping stays stored and untouched, and is counted (`UNREADABLE`); an endpoint with
# no adapter registered is a configuration problem, not a data problem, and gets its
# own answer (`UNVERIFIABLE`) rather than collapsing into `UNCHANGED`; and one run can
# report a mix of all four at once.
# ---------------------------------------------------------------------------


async def test_remap_repairs_a_mention_corrupted_after_collection_from_its_stored_payload_alone(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)

    mention = await _mention_by_external_id(db_session, title_id, OVERLAP_TWEET_ID)
    correct_text = mention.text
    correct_display_name = mention.author_display_name
    mention.text = "this is not what the post said"
    mention.author_display_name = "Wrong Display Name"
    await db_session.flush()

    unreachable_transport = FixtureTransport({})
    service = ReprocessService(db_session, FakeAnalyzer())

    result = await service.reprocess_title(title_id)

    assert result.remapped == 1
    assert unreachable_transport.calls == []

    await db_session.refresh(mention)
    assert mention.text == correct_text
    assert mention.author_display_name == correct_display_name


async def test_reprocess_title_reports_zero_remapped_and_unreadable_for_an_unchanged_corpus(
    db_session: AsyncSession,
) -> None:
    """A payload that is fine and unchanged reports `UNCHANGED` and must contribute to
    neither `remapped` nor `unreadable` — the third `_RemapOutcome` state, `UPDATED`, is
    the only one either counter should ever move for."""
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    service = ReprocessService(db_session, FakeAnalyzer())

    result = await service.reprocess_title(title_id)

    assert result.remapped == 0
    assert result.unreadable == 0


async def test_remap_reports_unchanged_and_does_not_dirty_a_mention_already_matching_its_payload(
    db_session: AsyncSession,
) -> None:
    """A more surgical check than the result-level assertion above: `_remap` must not
    call `setattr` at all when nothing differs, or every reprocess run would dirty
    every row it touched even when nothing moved."""
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)

    mention = await _mention_by_external_id(db_session, title_id, OVERLAP_TWEET_ID)
    mention_repo = MentionRepository(db_session)
    payload = (await mention_repo.payloads_for_mentions([mention.id]))[mention.id]
    service = ReprocessService(db_session, FakeAnalyzer())

    outcome = service._remap(mention, payload)

    assert outcome is _RemapOutcome.UNCHANGED
    assert sa_inspect(mention).modified is False


async def test_remap_with_no_adapter_registered_for_the_endpoint_is_unverifiable(
    db_session: AsyncSession,
) -> None:
    """A payload whose `endpoint_key` no longer resolves to any adapter (the mapping was
    retired, or the key was mistyped) is `_remap`'s fourth case, `UNVERIFIABLE`: nothing
    is wrong with the data, this application just currently has no way to check it, and
    the fix is to restore the adapter rather than investigate the post. It must not
    inflate `remapped` or `unreadable`, and the mention it belongs to is left exactly as
    it was."""
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)

    mention = await _mention_by_external_id(db_session, title_id, OVERLAP_TWEET_ID)
    original_text = mention.text
    mention_repo = MentionRepository(db_session)
    payload = (await mention_repo.payloads_for_mentions([mention.id]))[mention.id]
    payload.endpoint_key = "x.nonexistent_endpoint"
    await db_session.flush()

    service = ReprocessService(db_session, FakeAnalyzer())
    outcome = service._remap(mention, payload)
    assert outcome is _RemapOutcome.UNVERIFIABLE

    result = await service.reprocess_title(title_id)

    assert result.remapped == 0
    assert result.unreadable == 0
    assert result.unverifiable == 1

    await db_session.refresh(mention)
    assert mention.text == original_text


async def test_still_unreadable_payload_under_the_current_mapping_stays_stored_and_untouched(
    db_session: AsyncSession,
) -> None:
    """AC: 'A payload that is still unreadable under the current mapping stays stored
    and untouched ... so a later adapter version gets another chance at it.' Simulates
    a payload doctored after collection (a broken adapter mapping writing bad data, or
    storage corruption) while its mention row is left alone.

    `_remap` reports this as `_RemapOutcome.UNREADABLE`: it must count towards
    `unreadable` and NOT towards `remapped`, and it must not mutate the payload row at
    all — not `payload.payload`, and not even `normalization_error` (still exactly
    `None`, the value it started with, since this item was readable at collection
    time). Asserting `normalization_error` explicitly, not just `payload.payload`, is
    what would catch a regression where someone "helpfully" starts writing the error
    back onto a payload `_remap` could not read.
    """
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)

    mention = await _mention_by_external_id(db_session, title_id, OVERLAP_TWEET_ID)
    original_mention_text = mention.text
    mention_repo = MentionRepository(db_session)
    payload = (await mention_repo.payloads_for_mentions([mention.id]))[mention.id]
    original_normalization_error = payload.normalization_error
    assert original_normalization_error is None  # the precondition this test relies on
    broken_payload_json = _tikhub_item_with_screen_name_removed()
    payload.payload = broken_payload_json
    await db_session.flush()

    service = ReprocessService(db_session, FakeAnalyzer())
    result = await service.reprocess_title(title_id)

    assert result.remapped == 0
    # "and is counted": the AC's own wording for why this matters — an operator running
    # a reprocess needs to see how many payloads are still stuck, or a mapping fix has
    # no way to be measured as having worked.
    assert result.unreadable == 1

    # "stays stored and untouched": the corrupted payload is neither discarded nor
    # further mutated by the failed remap attempt, in either of its fields.
    await db_session.refresh(payload)
    assert payload.payload == broken_payload_json
    assert payload.normalization_error == original_normalization_error

    await db_session.refresh(mention)
    assert mention.text == original_mention_text


async def test_remap_of_an_already_flagged_unreadable_payload_still_leaves_its_error_untouched(
    db_session: AsyncSession,
) -> None:
    """The same `UNREADABLE` outcome, starting from a payload that already carried a
    `normalization_error` from some earlier annotation, to confirm `_remap` treats that
    field as read-only in both directions: it neither clears a pre-existing error (only
    an `UPDATED` repair does that) nor rewrites one that was already there."""
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)

    mention = await _mention_by_external_id(db_session, title_id, OVERLAP_TWEET_ID)
    mention_repo = MentionRepository(db_session)
    payload = (await mention_repo.payloads_for_mentions([mention.id]))[mention.id]
    broken_payload_json = _tikhub_item_with_screen_name_removed()
    payload.payload = broken_payload_json
    payload.normalization_error = "previously flagged as unreadable"
    await db_session.flush()

    service = ReprocessService(db_session, FakeAnalyzer())
    result = await service.reprocess_title(title_id)

    assert result.remapped == 0
    assert result.unreadable == 1
    await db_session.refresh(payload)
    assert payload.payload == broken_payload_json
    assert payload.normalization_error == "previously flagged as unreadable"


async def test_one_run_reports_repaired_unchanged_unreadable_and_unverifiable_counts_together(
    db_session: AsyncSession,
) -> None:
    """The test that would have caught the original bug at the level an operator
    actually reads: before the fix, a mix like this silently reported `unreadable=0`
    (or, after Finding 2's fix landed but before this test existed, `unverifiable=0`),
    hiding genuinely broken mentions in plain sight inside `examined`. One title, one
    run, four simultaneous outcomes: one mention repaired (`UPDATED`), one still broken
    (`UNREADABLE`), one whose endpoint has no adapter registered (`UNVERIFIABLE`), and
    the remaining seventeen untouched (`UNCHANGED`)."""
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)

    to_repair = await _mention_by_external_id(db_session, title_id, OVERLAP_TWEET_ID)
    to_repair.text = "corrupted after collection, needs repair"
    await db_session.flush()

    other_tweet_ids = [
        item["tweet_id"] for item in TIKHUB_ITEMS if item["tweet_id"] != OVERLAP_TWEET_ID
    ]
    broken_tweet_id, unverifiable_tweet_id = other_tweet_ids[0], other_tweet_ids[1]

    to_break = await _mention_by_external_id(db_session, title_id, broken_tweet_id)
    to_orphan = await _mention_by_external_id(db_session, title_id, unverifiable_tweet_id)
    mention_repo = MentionRepository(db_session)
    payloads = await mention_repo.payloads_for_mentions([to_break.id, to_orphan.id])
    payloads[to_break.id].payload = _tikhub_item_with_screen_name_removed(broken_tweet_id)
    payloads[to_orphan.id].endpoint_key = "x.nonexistent_endpoint"
    await db_session.flush()

    service = ReprocessService(db_session, FakeAnalyzer())
    result = await service.reprocess_title(title_id)

    assert result.examined == 20
    assert result.remapped == 1
    assert result.unreadable == 1
    assert result.unverifiable == 1
    assert result.missing_payload == 0

    await db_session.refresh(to_repair)
    assert to_repair.text != "corrupted after collection, needs repair"


# ---------------------------------------------------------------------------
# Section 6 — SQLite hands `posted_at` back naive while adapters produce tz-aware
# datetimes. A plain `!=` between them is silently unequal; `_differs`/`_as_utc` exist
# to compare them as instants instead.
# ---------------------------------------------------------------------------


def test_differs_treats_naive_and_aware_datetimes_at_the_same_instant_as_equal() -> None:
    naive = datetime(2026, 8, 11, 17, 41, 52)
    aware = datetime(2026, 8, 11, 17, 41, 52, tzinfo=UTC)

    assert _differs(naive, aware) is False
    # Documents exactly the trap `_differs` exists to avoid: a plain `!=` gets this
    # wrong, silently, on every comparison SQLite is involved in.
    assert (naive != aware) is True


def test_differs_still_reports_a_genuine_change_between_naive_and_aware_datetimes() -> None:
    naive = datetime(2026, 8, 11, 17, 41, 52)
    aware_different_instant = datetime(2026, 8, 11, 18, 0, 0, tzinfo=UTC)

    assert _differs(naive, aware_different_instant) is True


def test_as_utc_treats_a_naive_datetime_as_already_utc() -> None:
    naive = datetime(2026, 8, 11, 17, 41, 52)

    assert _as_utc(naive) == datetime(2026, 8, 11, 17, 41, 52, tzinfo=UTC)


async def test_reprocess_does_not_falsely_flag_remapped_due_to_sqlite_stripping_posted_at_tz(
    db_session: AsyncSession,
) -> None:
    """The end-to-end version of the trap above. `collect_page`'s own in-memory
    objects still hold the tz-aware value the adapter produced (the session's
    `expire_on_commit=False`), so `db_session.expire_all()` forces a genuine reload
    through SQLite before asserting the documented fact — confirmed independently in
    the task report by round-tripping a bare tz-aware column through aiosqlite.

    Sensitivity: with a plain `!=` in place of `_differs`, every mention's `posted_at`
    would compare unequal on every run (naive stored value vs. tz-aware recomputed
    value), so `remapped` would read 20 instead of 0 here.
    """
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)

    db_session.expire_all()
    stored_mention = await _mention_by_external_id(db_session, title_id, OVERLAP_TWEET_ID)
    assert stored_mention.posted_at.tzinfo is None

    result = await ReprocessService(db_session, FakeAnalyzer()).reprocess_title(title_id)

    assert result.remapped == 0


# ---------------------------------------------------------------------------
# Section 7 — The unconfigured analyzer refuses (a 503-style domain error) rather than
# writing null/neutral verdicts.
# ---------------------------------------------------------------------------


async def test_unconfigured_analyzer_refuses_rather_than_writing_neutral_verdicts(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    service = ReprocessService(db_session, UnconfiguredMentionAnalyzer())

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await service.reprocess_title(title_id)

    assert str(exc_info.value) == ANALYSIS_UNAVAILABLE_MESSAGE
    rows = (await db_session.execute(select(MentionAnalysis))).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# Section 8 — An analyzer that returns fewer verdicts than requested leaves the
# unjudged mentions without rows, so a later run can pick them up.
# ---------------------------------------------------------------------------


async def test_analyzer_returning_fewer_verdicts_than_requested_leaves_the_rest_unjudged(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    repo = MentionAnalysisRepository(db_session)

    partial_analyzer = FakeAnalyzer(version_name="partial-v1", verdict_limit=15)
    first = await ReprocessService(db_session, partial_analyzer).reprocess_title(title_id)

    assert first.analyzed == 15
    assert await repo.count_for_title(title_id, "partial-v1") == 15

    full_analyzer = FakeAnalyzer(version_name="partial-v1", verdict_limit=None)
    second = await ReprocessService(db_session, full_analyzer).reprocess_title(title_id)

    assert second.already_analyzed == 15
    assert second.analyzed == 5
    assert await repo.count_for_title(title_id, "partial-v1") == 20


# ---------------------------------------------------------------------------
# Section 9 — A title that does not exist is refused.
# ---------------------------------------------------------------------------


async def test_reprocessing_a_title_that_does_not_exist_is_refused(
    db_session: AsyncSession,
) -> None:
    analyzer = FakeAnalyzer()
    service = ReprocessService(db_session, analyzer)
    missing_title_id = uuid.uuid4()

    with pytest.raises(ResourceNotFoundError) as exc_info:
        await service.reprocess_title(missing_title_id)

    assert str(exc_info.value) == TITLE_NOT_FOUND_MESSAGE.format(id=missing_title_id)
    assert analyzer.calls == []


# ---------------------------------------------------------------------------
# Section 10 — Batching: `REPROCESS_BATCH_SIZE` is 200, and the corpus walk is
# keyset-paged. A corpus spanning several batches is covered without skipping or
# repeating any mention — including, per Finding 1 of the adversarial review, when
# `_remap` rewrites the very column the walk used to be paged by. The walk now pages
# by `Mention.id` (immutable) instead of `(posted_at, id)` precisely because a repair
# can move `posted_at` anywhere; the two tests below combine batching *and* remapping
# in one corpus, which the plain multi-batch test above cannot do, since its mentions
# have no stored payload and `_remap` short-circuits at `payload is None` for every one
# of them.
# ---------------------------------------------------------------------------


def test_reprocess_batch_size_is_200() -> None:
    assert REPROCESS_BATCH_SIZE == 200


async def test_reprocess_corpus_walk_covers_a_multi_batch_corpus_without_skipping_or_repeating(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reprocess_service_module, "REPROCESS_BATCH_SIZE", 5)
    title_id = await _create_title(db_session)
    await _add_synthetic_mentions(db_session, title_id, 23)

    analyzer = FakeAnalyzer(version_name="batch-walk")
    service = ReprocessService(db_session, analyzer)

    result = await service.reprocess_title(title_id)

    assert result.examined == 23
    assert result.analyzed == 23
    assert result.already_analyzed == 0
    assert result.missing_payload == 23

    # Every mention seen exactly once across all batches: neither skipped (23 unique
    # ids) nor repeated (23 total, matching the unique count).
    seen_mention_ids = [mention.mention_id for batch in analyzer.calls for mention in batch]
    assert len(seen_mention_ids) == 23
    assert len(set(seen_mention_ids)) == 23

    rows = (await db_session.execute(select(MentionAnalysis))).scalars().all()
    assert len(rows) == 23


async def test_reprocess_examines_the_whole_corpus_once_when_remap_shifts_a_posted_at_forward(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 1, forward direction: in the interim (partially fixed) implementation
    the task brief describes, a row shifted forward past the batch that produced the
    walk's cursor sorted after that cursor and was visited a second time
    (`examined=11 of 10`). Paging by `Mention.id` must make the direction irrelevant."""
    monkeypatch.setattr(reprocess_service_module, "REPROCESS_BATCH_SIZE", 5)
    monkeypatch.setattr(
        reprocess_service_module,
        "get_adapter",
        lambda endpoint_key: (
            _ShiftingAdapter() if endpoint_key == _SHIFTING_ENDPOINT_KEY else None
        ),
    )
    title_id = await _create_title(db_session)
    mentions = await _add_synthetic_mentions_with_payloads(db_session, title_id, 23)
    mention_repo = MentionRepository(db_session)
    payloads = await mention_repo.payloads_for_mentions([mention.id for mention in mentions])

    shifted_mention = mentions[0]
    shifted_payload = payloads[shifted_mention.id]
    far_future = datetime(2027, 1, 1, tzinfo=UTC)  # past every other mention in the corpus
    shifted_payload.payload = {**shifted_payload.payload, "posted_at": far_future.isoformat()}
    await db_session.flush()

    analyzer = FakeAnalyzer(version_name="shift-forward")
    result = await ReprocessService(db_session, analyzer).reprocess_title(title_id)

    assert result.examined == 23
    assert result.remapped == 1

    seen_mention_ids = [mention.mention_id for batch in analyzer.calls for mention in batch]
    assert len(seen_mention_ids) == 23
    assert len(set(seen_mention_ids)) == 23
    assert len((await db_session.execute(select(MentionAnalysis))).scalars().all()) == 23


async def test_reprocess_examines_the_whole_corpus_once_when_remap_shifts_a_posted_at_backward(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 1, backward direction — "the skip direction": in the original
    (unfixed) implementation, a cursor computed from a `posted_at` that had just moved
    backward could re-select or exclude rows incorrectly, and the reviewer reproduced a
    run that examined 5 of 10 mentions and reported success. Paging by `Mention.id`
    must make the direction irrelevant."""
    monkeypatch.setattr(reprocess_service_module, "REPROCESS_BATCH_SIZE", 5)
    monkeypatch.setattr(
        reprocess_service_module,
        "get_adapter",
        lambda endpoint_key: (
            _ShiftingAdapter() if endpoint_key == _SHIFTING_ENDPOINT_KEY else None
        ),
    )
    title_id = await _create_title(db_session)
    mentions = await _add_synthetic_mentions_with_payloads(db_session, title_id, 23)
    mention_repo = MentionRepository(db_session)
    payloads = await mention_repo.payloads_for_mentions([mention.id for mention in mentions])

    shifted_mention = mentions[-1]
    shifted_payload = payloads[shifted_mention.id]
    far_past = datetime(2020, 1, 1, tzinfo=UTC)  # before every other mention in the corpus
    shifted_payload.payload = {**shifted_payload.payload, "posted_at": far_past.isoformat()}
    await db_session.flush()

    analyzer = FakeAnalyzer(version_name="shift-backward")
    result = await ReprocessService(db_session, analyzer).reprocess_title(title_id)

    assert result.examined == 23
    assert result.remapped == 1

    seen_mention_ids = [mention.mention_id for batch in analyzer.calls for mention in batch]
    assert len(seen_mention_ids) == 23
    assert len(set(seen_mention_ids)) == 23
    assert len((await db_session.execute(select(MentionAnalysis))).scalars().all()) == 23


# ---------------------------------------------------------------------------
# Section 11 — Durability. The shared `db_session` fixture hands every call in a test
# the SAME open session, which would mask a missing `session.commit()` inside
# `reprocess_title` the same way it masked the E03-S07 regression documented in
# `test_provider_agnostic_collection_interface.py` (Section 12 there). This test uses
# its own file-backed SQLite database and two independent sessions, so the writes are
# observed from a session that did not perform them — covering both derived-field
# durability (new `MentionAnalysis` rows) and remap-repair durability (a corrected
# `Mention.text`) in the one run that is supposed to produce both.
# ---------------------------------------------------------------------------


async def test_reprocess_title_commits_so_a_second_independent_session_sees_its_writes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "reprocess_durability.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as writer_session:
            title_id = await _create_title(writer_session)
            await writer_session.commit()

            await _collect_tikhub_corpus(writer_session, title_id)

            mention = await _mention_by_external_id(writer_session, title_id, OVERLAP_TWEET_ID)
            mention.text = "corrupted after collection, to be repaired by reprocess"
            await writer_session.flush()
            # Deliberately no explicit commit here: whether the writes below are
            # observed by the reader session depends entirely on whether
            # `reprocess_title` committed them itself.

            analyzer = FakeAnalyzer(version_name="durable-v1")
            await ReprocessService(writer_session, analyzer).reprocess_title(title_id)

        async with session_factory() as reader_session:
            analyses = (
                (
                    await reader_session.execute(
                        select(MentionAnalysis).where(MentionAnalysis.title_id == title_id)
                    )
                )
                .scalars()
                .all()
            )
            repaired_mention = await _mention_by_external_id(
                reader_session, title_id, OVERLAP_TWEET_ID
            )
    finally:
        await engine.dispose()

    assert len(analyses) == 20
    assert {row.pipeline_version for row in analyses} == {"durable-v1"}
    assert repaired_mention.text != "corrupted after collection, to be repaired by reprocess"


# ---------------------------------------------------------------------------
# Section 12 — Finding 4 (adversarial review): a single commit at the end of the whole
# walk meant a late failure over a six-week corpus discarded every repair and verdict
# computed before it. `reprocess_title` now commits per batch. This needs the
# file-backed, two-independent-session pattern to be meaningful, the same reason
# Section 11 does — the shared `db_session` fixture's one open session cannot tell
# "committed" apart from "merely flushed".
# ---------------------------------------------------------------------------


async def test_a_run_that_fails_partway_leaves_completed_batches_committed_and_resumable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """15 synthetic mentions, batch size 5 (3 batches), an analyzer that raises on its
    3rd call. The first two batches (10 mentions) must be durably committed despite the
    run dying on the third, and a later run with a working analyzer must skip those 10
    as already analysed and pick up only the remaining 5 — resuming, not redoing."""
    monkeypatch.setattr(reprocess_service_module, "REPROCESS_BATCH_SIZE", 5)

    db_path = tmp_path / "reprocess_partial_failure.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as setup_session:
            title_id = await _create_title(setup_session)
            await setup_session.commit()
            await _add_synthetic_mentions(setup_session, title_id, 15)
            await setup_session.commit()

        async with session_factory() as failing_session:
            failing_analyzer = FailingAfterNBatchesAnalyzer(
                version_name="resumable-v1", fail_after_batches=2
            )
            with pytest.raises(RuntimeError):
                await ReprocessService(failing_session, failing_analyzer).reprocess_title(
                    title_id
                )
            # Deliberately no commit/rollback here: the failing session is simply
            # closed, exactly as an unhandled exception in a real process would leave
            # it, so only what `reprocess_title` itself committed survives.

        async with session_factory() as after_failure_session:
            committed_rows = (
                (
                    await after_failure_session.execute(
                        select(MentionAnalysis).where(MentionAnalysis.title_id == title_id)
                    )
                )
                .scalars()
                .all()
            )
        assert len(committed_rows) == 10  # two committed batches; the third never landed

        async with session_factory() as resuming_session:
            resuming_analyzer = FakeAnalyzer(version_name="resumable-v1")
            resume_result = await ReprocessService(
                resuming_session, resuming_analyzer
            ).reprocess_title(title_id)

        async with session_factory() as final_session:
            final_rows = (
                (
                    await final_session.execute(
                        select(MentionAnalysis).where(MentionAnalysis.title_id == title_id)
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()

    assert resume_result.already_analyzed == 10
    assert resume_result.analyzed == 5
    assert len(final_rows) == 15


# ---------------------------------------------------------------------------
# Section 13 — Finding 3 (adversarial review): there was no way to trigger a reprocess
# outside a Python shell. `scripts/reprocess_title.py` (with `make reprocess
# title=<uuid> [from=YYYY-MM-DD] [until=YYYY-MM-DD]`) is the fix. These tests exercise
# the script's own logic — `_parse_day` and the `_build_parser` wiring — directly,
# never by running the script against a real database.
# ---------------------------------------------------------------------------


def test_parse_day_reads_a_valid_calendar_day_as_midnight_utc() -> None:
    assert _parse_day("2026-08-11", end_of_day=False) == datetime(2026, 8, 11, tzinfo=UTC)


def test_parse_day_with_end_of_day_is_inclusive_to_the_last_instant_of_that_day() -> None:
    """`--until 2026-08-11` means the whole of the 11th, not midnight at its start — the
    reading anyone typing a date expects, and the one that stops a day's posts being
    silently excluded from their own window."""
    assert _parse_day("2026-08-11", end_of_day=True) == datetime(
        2026, 8, 11, 23, 59, 59, 999999, tzinfo=UTC
    )


def test_parse_day_rejects_a_malformed_date() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_day("11-08-2026", end_of_day=False)


def test_build_parser_requires_a_title_id_and_parses_it_as_a_uuid() -> None:
    parser = _build_parser()
    title_id = uuid.uuid4()

    arguments = parser.parse_args(["--title-id", str(title_id)])

    assert arguments.title_id == title_id
    assert arguments.posted_from is None
    assert arguments.posted_until is None


def test_build_parser_without_a_title_id_exits_nonzero() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_parser_wires_from_and_until_through_parse_day() -> None:
    parser = _build_parser()

    arguments = parser.parse_args(
        ["--title-id", str(uuid.uuid4()), "--from", "2026-07-01", "--until", "2026-08-11"]
    )

    assert arguments.posted_from == datetime(2026, 7, 1, tzinfo=UTC)
    assert arguments.posted_until == datetime(2026, 8, 11, 23, 59, 59, 999999, tzinfo=UTC)


def test_build_parser_rejects_a_malformed_from_date_at_parse_time() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--title-id", str(uuid.uuid4()), "--from", "not-a-date"])


# ---------------------------------------------------------------------------
# Section 14 — Finding 5 (adversarial review): `MentionAnalysisRepository
# .delete_for_title_and_version` — "the undo for a bad model run" — had no coverage at
# all. It must remove only the named version's rows, leave every other version and the
# corpus (mentions and raw payloads) untouched, report how many rows it removed, and
# leave the corpus in a state the deleted version can be recomputed from with zero
# collection spend.
# ---------------------------------------------------------------------------


async def test_delete_for_title_and_version_removes_only_the_named_versions_rows(
    db_session: AsyncSession,
) -> None:
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    repo = MentionAnalysisRepository(db_session)

    await ReprocessService(db_session, FakeAnalyzer(version_name="bad-v1")).reprocess_title(
        title_id
    )
    await ReprocessService(db_session, FakeAnalyzer(version_name="good-v2")).reprocess_title(
        title_id
    )
    assert await repo.count_for_title(title_id, "bad-v1") == 20
    assert await repo.count_for_title(title_id, "good-v2") == 20

    deleted = await repo.delete_for_title_and_version(title_id, "bad-v1")
    await db_session.commit()

    assert deleted == 20
    assert await repo.count_for_title(title_id, "bad-v1") == 0
    # The other version is untouched, both in count and in row identity.
    good_rows = await repo.list_for_title(title_id, "good-v2", limit=100)
    assert len(good_rows) == 20

    # Neither the mentions nor their raw payloads — the corpus itself — are touched by
    # the undo: it discards only the derived judgement, never what was collected.
    mentions = (
        (await db_session.execute(select(Mention).where(Mention.title_id == title_id)))
        .scalars()
        .all()
    )
    assert len(mentions) == 20
    mention_repo = MentionRepository(db_session)
    payloads = await mention_repo.payloads_for_mentions([mention.id for mention in mentions])
    assert len(payloads) == 20


async def test_delete_for_title_and_version_leaves_the_corpus_recomputable_with_zero_spend(
    db_session: AsyncSession,
) -> None:
    """The undo's whole point: after discarding a bad model's verdicts, the same
    version can be recomputed from stored payloads alone. Proven the same structural
    way as Section 1 — a working transport exists in the test's world and is never
    reached by the service that does the recomputing."""
    title_id = await _create_title(db_session)
    await _collect_tikhub_corpus(db_session, title_id)
    repo = MentionAnalysisRepository(db_session)

    await ReprocessService(db_session, FakeAnalyzer(version_name="bad-v1")).reprocess_title(
        title_id
    )
    deleted = await repo.delete_for_title_and_version(title_id, "bad-v1")
    await db_session.commit()
    assert deleted == 20
    assert await repo.count_for_title(title_id, "bad-v1") == 0

    unreachable_transport = FixtureTransport({"x.tikhub_search_timeline": TIKHUB_RESPONSE})
    recomputed = await ReprocessService(
        db_session, FakeAnalyzer(version_name="bad-v1")
    ).reprocess_title(title_id)

    assert unreachable_transport.calls == []
    assert recomputed.has_spent_nothing is True
    assert recomputed.analyzed == 20
    assert await repo.count_for_title(title_id, "bad-v1") == 20

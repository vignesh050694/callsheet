"""Tests for E02-S05 — Exclude a colliding term so unrelated franchise chatter stops
polluting my numbers.

Story: stories/E02-title-setup-identity-discovery/E02-S05-exclude-contaminating-terms.md
Epic: stories/E02-title-setup-identity-discovery/EPIC.md

The story has exactly one Gherkin scenario, "Owner excludes a colliding franchise term
after seeing it in the mentions feed", and it maps to exactly one test:

  - `test_owner_excludes_a_colliding_franchise_term_after_seeing_it_in_the_mentions_feed`
    covers every Given in order (a feed of posts including an unrelated franchise; every
    post carrying the evidence a "Not my title" action needs — `matched_terms` and
    `candidate_exclusion_terms`; the impact screen's pre-confirmation count), the When
    (confirming the exclusion), and each of the compound Then's three separate promises,
    pinned as three separate blocks inside the one test: (1) matching mentions are removed
    from every count and chart *from that point on*, (2) the removal reaches historic
    mentions — ones collected before the rule existed, (3) future collection stops
    matching them, driven through `CollectionService.collect_page` with a fresh post the
    title has never seen.

Five more tests, at the budget's cap, chosen for where this story is most likely to be
wrong given the codebase's own defect history and the story's own shape:

  - `test_future_collection_stops_matching_excluded_terms_through_a_real_collection_cycle`
    drives promise 3 a second time, through a genuine scheduled cycle
    (`CollectionRunService.execute_run`, via the `SequencedTikhubTransport` harness
    `test_collection_starts_and_counts_once.py` built for exactly this) rather than a
    direct `CollectionService` call, so the wiring in `collection_run_service.py` that
    reads `TitleService.excluded_terms_for(title)` is exercised for real.
  - `test_lifting_one_of_two_excluded_terms_leaves_a_post_excluded_by_the_remaining_rule`
    — a post carrying two disowned franchises must stay excluded, credited to the rule
    that still bites, when only one of the two is lifted.
  - `test_exclusion_word_boundary_does_not_match_a_substring_inside_an_indic_word` — the
    exact regression `app/core/post_matching.py`'s own docstring names (`தமிழ` must not
    match inside `தமிழா`), applied to the exclusion path rather than the matched-terms path.
  - `test_exclusion_value_over_the_column_bound_after_nfkc_expansion_is_rejected` — NFKC
    expansion can push a value that passed the request schema's raw `max_length` past the
    stored column bound; SQLite does not enforce it, so only an explicit assertion catches
    a regression here.
  - `test_impact_count_is_measured_over_the_whole_corpus_beyond_one_sweep_batch` — the
    impact count and the corpus sweep both walk in batches of
    `EXCLUSION_SWEEP_BATCH_SIZE`; a corpus larger than one batch has to be summed
    correctly across the boundary, not just counted within the first page.

No test calls Monid. Posts that need to already be "collected" are seeded directly as
`Mention` rows over `db_session`, exactly as `test_collection_starts_and_counts_once.py`
Section 3b does for the same reason: they are meant to model a corpus collection already
produced, not to exercise collection itself.

---

Three more tests (a second round, budget of 3) cover a since-fixed reviewer finding:
`MentionFeedService.list_mentions` used to gate the feed with `require_owning_organization`
-- the check `title_access.py`'s own docstring reserves for surfaces describing *other
people's* relationship to a title (the member list, the access log). The mentions feed is
the title's core content, the same category as collection status, which uses
`require_readable`. It now does too, followed by `_ensure_feed_is_whole_for`, which refuses
only the one shared role promised a genuinely narrower view.

Placed in this file rather than `test_grant_agency_scoped_access.py` or
`test_artist_accepts_invite_and_links_profile.py`: the finding is about the mentions feed
this story (E02-S05) owns, not about sharing or invitation acceptance, and this file already
imports collaborator test modules for their setup helpers (see above) rather than
duplicating them, so doing the same here keeps one pattern rather than starting a second.

  - `test_agency_manager_reads_mentions_feed_but_cannot_reach_exclusion_controls` -- the
    concrete failure the finding named: an agency manager holding an active share (setup
    reused from `test_grant_agency_scoped_access.py`) reads the feed with a 200, and is
    still refused the exclusion write endpoints with a 403 -- reading is now open, editing
    setup still is not.
  - `test_tagged_artist_who_accepted_invite_gets_403_on_mentions_feed` -- the other shared
    role gets the opposite answer: a tagged artist who accepted their invitation (setup
    reused from `test_artist_accepts_invite_and_links_profile.py`) gets a 403 that names the
    scope, neither the 200 the agency gets nor the 404 a stranger gets.
  - `test_stranger_still_gets_404_on_mentions_feed` -- the regression `_ensure_feed_is_whole_for`
    must not introduce: a caller with no relationship to the title at all still gets the
    plain 404 a missing title gets, not the artist's 403.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.collection_endpoints import get_endpoint
from app.core.platforms import Platform
from app.models.collection_run import CollectionRunStatus
from app.models.mention import Mention
from app.models.title import TITLE_TERM_MAX_LENGTH
from app.repositories.mention_repository import MentionRepository
from app.repositories.title_repository import TitleRepository
from app.services.collection.mention_shape import NormalizedMention
from app.services.collection.source import CollectedItem, CollectionPage, CollectionSource
from app.services.collection_service import CollectionService
from app.services.mention_feed_service import ARTIST_SCOPED_FEED_MESSAGE
from app.services.title_exclusion_service import EXCLUSION_SWEEP_BATCH_SIZE
from app.services.title_service import TitleService
from tests.test_artist_accepts_invite_and_links_profile import ACCEPT_URL, _as, _create_user, _tag
from tests.test_collection_starts_and_counts_once import (
    SequencedTikhubTransport,
    _build_run_service,
    _pending_run,
    _tweet_item,
)
from tests.test_grant_agency_scoped_access import AGENCY_PAYLOAD, _share
from tests.test_grant_agency_scoped_access import (
    _create_organization as _create_agency_organization,
)

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
BASE_TIME = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


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


def _mention(
    title_id: uuid.UUID,
    external_id: str,
    *,
    text: str,
    hashtags: list[str] | None = None,
    posted_at: datetime,
) -> Mention:
    """One already-collected post, shaped for the exclusion path: only what
    `term_occurs_in` and the repository counts read."""
    return Mention(
        title_id=title_id,
        platform=Platform.X,
        external_id=external_id,
        author_handle="fan",
        author_display_name="Fan",
        text=text,
        hashtags=hashtags or [],
        posted_at=posted_at,
        collected_at=posted_at,
    )


class _StaticCollectionSource(CollectionSource):
    """A `CollectionSource` double that hands back one pre-built page, standing in for a
    poll that just found a brand new post — the seam promise 3 needs, without going
    through a provider adapter to get there."""

    def __init__(self, page: CollectionPage) -> None:
        self._page = page

    async def fetch(
        self, platform: Platform, query: str, *, page: str | None = None, limit: int
    ) -> CollectionPage:
        return self._page


# ---------------------------------------------------------------------------
# The scenario: "Owner excludes a colliding franchise term after seeing it in the
# mentions feed" — every Given, the When, and the compound Then's three promises.
# ---------------------------------------------------------------------------


async def test_owner_excludes_a_colliding_franchise_term_after_seeing_it_in_the_mentions_feed(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)
    title_id = uuid.UUID(
        await _create_title(
            api_client,
            organization_id,
            _title_payload(name="DC", directors=["Lokesh Kanagaraj"]),
        )
    )

    # Given: my title's mentions feed contains posts tagged with an unrelated franchise —
    # three posts carry the studio's own short name *and* a comics franchise hashtag that
    # collides with it, alongside two posts that are genuinely about the film.
    contaminated_mentions = [
        _mention(
            title_id,
            f"contam-{index}",
            text="Can't wait for the #DC #DareDevil crossover fan poster",
            hashtags=["DC", "DareDevil"],
            posted_at=BASE_TIME + timedelta(minutes=index),
        )
        for index in range(3)
    ]
    clean_mentions = [
        _mention(
            title_id,
            f"clean-{index}",
            text="First look poster for DC drops today",
            hashtags=["DC"],
            posted_at=BASE_TIME + timedelta(hours=1, minutes=index),
        )
        for index in range(2)
    ]
    db_session.add_all([*contaminated_mentions, *clean_mentions])
    await db_session.commit()
    contaminated_ids = {str(mention.id) for mention in contaminated_mentions}
    clean_ids = {str(mention.id) for mention in clean_mentions}

    # Given: every post in the feed has a "Not my title" action — backed by every item
    # carrying `matched_terms` (why it is here) and the contaminated ones offering
    # `#DareDevil` as the candidate that dragged them in.
    feed_before = await api_client.get(f"/api/v1/titles/{title_id}/mentions", params={"limit": 10})
    assert feed_before.status_code == 200
    feed_before_body = feed_before.json()
    assert {item["id"] for item in feed_before_body["items"]} == contaminated_ids | clean_ids
    for item in feed_before_body["items"]:
        assert item["matched_terms"], "every post needs evidence for the 'Not my title' action"
    contaminated_items = [
        item for item in feed_before_body["items"] if item["id"] in contaminated_ids
    ]
    assert len(contaminated_items) == 3
    for item in contaminated_items:
        assert "#DareDevil" in item["candidate_exclusion_terms"]

    # Given: the exclusion screen shows how many already-collected mentions the rule would
    # remove, before anything is confirmed.
    impact = await api_client.post(
        f"/api/v1/titles/{title_id}/exclusions/impact", json={"value": "DareDevil"}
    )
    assert impact.status_code == 200
    impact_body = impact.json()
    assert impact_body["would_remove"] == 3
    assert impact_body["counted_now"] == 5
    assert impact_body["is_already_excluded"] is False
    assert impact_body["removes_everything"] is False
    assert 1 <= len(impact_body["samples"]) <= 3

    # When: I confirm the exclusion term.
    created = await api_client.post(
        f"/api/v1/titles/{title_id}/exclusions", json={"value": "DareDevil"}
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["removed_mentions"] == 3
    assert created_body["term"]["value"] == "DareDevil"

    # Then, promise 1 of 3: matching mentions are removed from all counts and charts for
    # this title from that point on.
    feed_after = await api_client.get(f"/api/v1/titles/{title_id}/mentions", params={"limit": 10})
    feed_after_body = feed_after.json()
    assert feed_after_body["counted_total"] == 2
    assert feed_after_body["collected_total"] == 5
    status_after = await api_client.get(f"/api/v1/titles/{title_id}/collection")
    assert status_after.json()["unsegmented_mention_count"] == 2

    # Then, promise 2 of 3: historic mentions included — the three posts were collected
    # before the rule existed, and the default feed drops exactly them, while the
    # "show what a rule removed" view still finds them, marked rather than deleted.
    assert {item["id"] for item in feed_after_body["items"]} == clean_ids
    feed_with_excluded = await api_client.get(
        f"/api/v1/titles/{title_id}/mentions",
        params={"limit": 10, "include_excluded": "true"},
    )
    feed_with_excluded_body = feed_with_excluded.json()
    assert {item["id"] for item in feed_with_excluded_body["items"]} == contaminated_ids | clean_ids
    for item in feed_with_excluded_body["items"]:
        if item["id"] in contaminated_ids:
            assert item["excluded_by_term"] == "daredevil"
            assert item["excluded_at"] is not None
        else:
            assert item["excluded_by_term"] is None

    # Then, promise 3 of 3: future collection stops matching them. A page arrives carrying
    # a post the title has never seen, contaminated the same way, run through
    # `CollectionService.collect_page` with this title's real, freshly-loaded exclusion
    # terms — the same mechanism the corpus sweep above used, seen from the arrival side.
    title = await TitleRepository(db_session).get_by_id(title_id)
    assert title is not None
    excluded_terms = TitleService.excluded_terms_for(title)
    assert excluded_terms == ["daredevil"]

    endpoint = get_endpoint("x.tikhub_search_timeline")
    assert endpoint is not None
    future_post = NormalizedMention(
        platform=Platform.X,
        external_id="future-1",
        text="Fresh #DareDevil crossover fanart, unrelated to the DC film",
        posted_at=datetime.now(UTC),
        author_handle="futurefan",
        author_display_name="Future Fan",
    )
    page = CollectionPage(
        platform=Platform.X,
        endpoint=endpoint,
        adapter_version="test",
        items=[
            CollectedItem(
                raw_payload={"id": "future-1"}, external_id="future-1", mention=future_post
            )
        ],
    )
    collection_service = CollectionService(db_session, _StaticCollectionSource(page))

    result = await collection_service.collect_page(
        title_id, Platform.X, "DC", limit=10, excluded_terms=excluded_terms
    )

    # The payload is retained — stored, not refused — but never reaches a count.
    assert result.stored == 1
    future_row = (
        await db_session.execute(select(Mention).where(Mention.external_id == "future-1"))
    ).scalar_one()
    assert future_row.excluded_by_term == "daredevil"
    assert future_row.excluded_at is not None

    mention_repository = MentionRepository(db_session)
    assert await mention_repository.count_for_title(title_id) == 2
    assert await mention_repository.count_for_title_including_excluded(title_id) == 6


# ---------------------------------------------------------------------------
# Promise 3, driven a second time through a real scheduled collection cycle rather than a
# direct `CollectionService` call, so `collection_run_service.py`'s own wiring of
# `TitleService.excluded_terms_for(title)` into `collect_page` is exercised for real.
# ---------------------------------------------------------------------------


async def test_future_collection_stops_matching_excluded_terms_through_a_real_collection_cycle(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)
    title_id = uuid.UUID(
        await _create_title(
            api_client,
            organization_id,
            _title_payload(name="DC", directors=["Lokesh Kanagaraj"], exclusions=["DareDevil"]),
        )
    )

    # One page, reused for every query variant this title's auto-queued first cycle plans
    # (`SequencedTikhubTransport` cycles back to it) — two posts, one clean and one
    # carrying the excluded franchise.
    response = {
        "status": "ok",
        "timeline": [
            _tweet_item("clean-1", text="Great DC teaser trailer out now"),
            _tweet_item("contam-1", text="#DC #DareDevil fan crossover, not related"),
        ],
        "next_cursor": None,
    }
    transport = SequencedTikhubTransport([response])
    service = _build_run_service(db_session, transport)

    result = await service.execute_run(await _pending_run(db_session, title_id))

    assert result.status is CollectionRunStatus.SUCCEEDED

    mention_repository = MentionRepository(db_session)
    # Both posts are retained — collection never refuses a page for what it contains.
    assert await mention_repository.count_for_title_including_excluded(title_id) == 2
    # Only the clean one counts.
    assert await mention_repository.count_for_title(title_id) == 1

    contam_mention = (
        await db_session.execute(select(Mention).where(Mention.external_id == "contam-1"))
    ).scalar_one()
    assert contam_mention.excluded_by_term == "daredevil"
    assert contam_mention.excluded_at is not None

    clean_mention = (
        await db_session.execute(select(Mention).where(Mention.external_id == "clean-1"))
    ).scalar_one()
    assert clean_mention.excluded_by_term is None


# ---------------------------------------------------------------------------
# A post disowned by two rules at once must stay disowned — credited to whichever rule
# still applies — when only one of the two is lifted.
# ---------------------------------------------------------------------------


async def test_lifting_one_of_two_excluded_terms_leaves_a_post_excluded_by_the_remaining_rule(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)
    title_id = uuid.UUID(await _create_title(api_client, organization_id, _title_payload()))

    mention = _mention(
        title_id,
        "double-contam-1",
        text="Nova crossover post carrying #DareDevil and #Batman both",
        hashtags=["DareDevil", "Batman"],
        posted_at=BASE_TIME,
    )
    db_session.add(mention)
    await db_session.commit()

    first = await api_client.post(
        f"/api/v1/titles/{title_id}/exclusions", json={"value": "DareDevil"}
    )
    assert first.status_code == 201
    assert first.json()["removed_mentions"] == 1

    # The post is already excluded, so the second rule's sweep finds nothing left to mark
    # — it still applies, it just never got the chance to be the one credited yet.
    second = await api_client.post(
        f"/api/v1/titles/{title_id}/exclusions", json={"value": "Batman"}
    )
    assert second.status_code == 201
    assert second.json()["removed_mentions"] == 0

    exclusions = (await api_client.get(f"/api/v1/titles/{title_id}/exclusions")).json()
    daredevil_term_id = next(term["id"] for term in exclusions if term["value"] == "DareDevil")

    removal = await api_client.delete(f"/api/v1/titles/{title_id}/exclusions/{daredevil_term_id}")
    assert removal.status_code == 200
    # Nothing comes back — Batman still disqualifies the post.
    assert removal.json()["restored_mentions"] == 0

    assert mention.excluded_by_term == "batman"
    assert mention.excluded_at is not None
    assert await MentionRepository(db_session).count_for_title(title_id) == 0

    remaining = (await api_client.get(f"/api/v1/titles/{title_id}/exclusions")).json()
    assert [term["value"] for term in remaining] == ["Batman"]


# ---------------------------------------------------------------------------
# Word boundaries: an exclusion must not match a substring inside a marked Indic word —
# the exact case `app/core/post_matching.py`'s own docstring names, applied to the
# exclusion path rather than the matched-terms path it was written for.
# ---------------------------------------------------------------------------


async def test_exclusion_word_boundary_does_not_match_a_substring_inside_an_indic_word(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)
    title_id = uuid.UUID(await _create_title(api_client, organization_id, _title_payload()))

    # "தமிழா" carries a trailing spacing vowel sign after "தமிழ" — a different word, not
    # the term with something appended.
    non_match = _mention(
        title_id,
        "tamil-non-match",
        text="தமிழா movie review, nothing about the term itself",
        hashtags=["தமிழா"],
        posted_at=BASE_TIME,
    )
    # "தமிழ" appears here as its own whole word.
    match = _mention(
        title_id,
        "tamil-match",
        text="இது ஒரு தமிழ படம்",
        hashtags=["தமிழ"],
        posted_at=BASE_TIME + timedelta(minutes=1),
    )
    db_session.add_all([non_match, match])
    await db_session.commit()

    impact = await api_client.post(
        f"/api/v1/titles/{title_id}/exclusions/impact", json={"value": "தமிழ"}
    )
    assert impact.status_code == 200
    impact_body = impact.json()
    assert impact_body["counted_now"] == 2
    assert impact_body["would_remove"] == 1

    created = await api_client.post(f"/api/v1/titles/{title_id}/exclusions", json={"value": "தமிழ"})
    assert created.status_code == 201
    assert created.json()["removed_mentions"] == 1

    assert non_match.excluded_by_term is None
    assert match.excluded_by_term == "தமிழ"


# ---------------------------------------------------------------------------
# NFKC expansion: a value that fits the request schema's raw `max_length` can still
# overflow the stored column once ligatures expand — SQLite does not enforce VARCHAR
# limits, so only an explicit length assertion catches a regression here.
# ---------------------------------------------------------------------------


async def test_exclusion_value_over_the_column_bound_after_nfkc_expansion_is_rejected(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    title_id = uuid.UUID(await _create_title(api_client, organization_id, _title_payload()))

    # U+FB01 (LATIN SMALL LIGATURE FI) is one code point that NFKC-expands to two ASCII
    # characters. 151 copies pass the request schema's raw `max_length=300` check but
    # expand to 302 characters — one over `TITLE_TERM_MAX_LENGTH`.
    oversized_value = "ﬁ" * 151
    assert len(oversized_value) <= TITLE_TERM_MAX_LENGTH

    impact = await api_client.post(
        f"/api/v1/titles/{title_id}/exclusions/impact", json={"value": oversized_value}
    )
    assert impact.status_code == 422
    assert "expanded to their standard form" in impact.json()["message"]

    created = await api_client.post(
        f"/api/v1/titles/{title_id}/exclusions", json={"value": oversized_value}
    )
    assert created.status_code == 422
    assert "expanded to their standard form" in created.json()["message"]


# ---------------------------------------------------------------------------
# The impact count is measured over the whole corpus, not one sweep batch —
# `EXCLUSION_SWEEP_BATCH_SIZE` posts is not the ceiling on what a rule can be told about.
# ---------------------------------------------------------------------------


async def test_impact_count_is_measured_over_the_whole_corpus_beyond_one_sweep_batch(
    db_session: AsyncSession, api_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)
    title_id = uuid.UUID(await _create_title(api_client, organization_id, _title_payload()))

    total = EXCLUSION_SWEEP_BATCH_SIZE + 50
    contaminated_flags = [index % 4 == 0 for index in range(total)]
    expected_contaminated = sum(contaminated_flags)
    # Sanity on the fixture itself: contamination has to straddle the batch boundary for
    # this test to actually exercise more than one sweep page.
    assert 0 < expected_contaminated < total
    assert any(
        flag for index, flag in enumerate(contaminated_flags) if index >= EXCLUSION_SWEEP_BATCH_SIZE
    )

    mentions = [
        _mention(
            title_id,
            f"bulk-{index}",
            text=(
                "Rival franchise crossover post #RivalFranchise"
                if is_contaminated
                else "Ordinary Nova conversation, nothing else here"
            ),
            posted_at=BASE_TIME + timedelta(seconds=index),
        )
        for index, is_contaminated in enumerate(contaminated_flags)
    ]
    db_session.add_all(mentions)
    await db_session.commit()

    impact = await api_client.post(
        f"/api/v1/titles/{title_id}/exclusions/impact", json={"value": "RivalFranchise"}
    )
    assert impact.status_code == 200
    impact_body = impact.json()
    assert impact_body["counted_now"] == total
    assert impact_body["would_remove"] == expected_contaminated

    created = await api_client.post(
        f"/api/v1/titles/{title_id}/exclusions", json={"value": "RivalFranchise"}
    )
    assert created.status_code == 201
    assert created.json()["removed_mentions"] == expected_contaminated
    assert (
        await MentionRepository(db_session).count_for_title(title_id)
        == total - expected_contaminated
    )


# ---------------------------------------------------------------------------
# Reviewer finding: the mentions feed used to gate on `require_owning_organization`, a
# check meant for surfaces describing *other people's* relationship to a title. It now
# gates on `require_readable` plus a narrower carve-out for the one shared role promised
# less. The three tests below cover exactly the three outcomes that changed: the agency
# manager's feed access is new (200), the tagged artist's feed access is refused with an
# explanation rather than silently narrowed (403), and the stranger's outcome must not
# have regressed (404).
# ---------------------------------------------------------------------------


async def test_agency_manager_reads_mentions_feed_but_cannot_reach_exclusion_controls(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    """The concrete failure the finding named: an agency manager granted access via E01-S05's
    sharing flow clicks the Mentions link and must see the feed (E01-S05 promises "reads and
    exports this title only"), while the exclusion write endpoints -- title setup -- stay
    owner-only, per `require_administrable` in `title_exclusion_service.py`."""
    organization_id = await _create_organization(api_client)
    title_id = uuid.UUID(await _create_title(api_client, organization_id, _title_payload()))
    agency_organization_id = await _create_agency_organization(other_api_client, AGENCY_PAYLOAD)
    share_response = await _share(api_client, str(title_id), agency_organization_id)
    assert share_response.status_code == 201, share_response.text

    feed = await other_api_client.get(f"/api/v1/titles/{title_id}/mentions", params={"limit": 10})
    assert feed.status_code == 200, feed.text
    assert feed.json()["items"] == []

    impact_attempt = await other_api_client.post(
        f"/api/v1/titles/{title_id}/exclusions/impact", json={"value": "SomeTerm"}
    )
    assert impact_attempt.status_code == 403, impact_attempt.text
    assert impact_attempt.json()["code"] == "PermissionDeniedError"

    create_attempt = await other_api_client.post(
        f"/api/v1/titles/{title_id}/exclusions", json={"value": "SomeTerm"}
    )
    assert create_attempt.status_code == 403, create_attempt.text
    assert create_attempt.json()["code"] == "PermissionDeniedError"


async def test_tagged_artist_who_accepted_invite_gets_403_on_mentions_feed(
    api_client: AsyncClient, unauthenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The other shared role's promise is genuinely narrower -- "sees only mentions that
    also name them", a filtered view E06 has not built yet. Serving the whole feed would
    over-share; a 404 would deny a title the artist can see. The feed must answer 403 with
    the scope message, matching neither the agency's 200 nor the stranger's 404."""
    organization_id = await _create_organization(api_client)
    title_id = uuid.UUID(
        await _create_title(
            api_client, organization_id, _title_payload(lead_cast=["Anirudh Ravichandran"])
        )
    )
    tagged = await _tag(
        api_client,
        str(title_id),
        artist_name="Anirudh Ravichandran",
        contact_email="anirudh@example.com",
    )
    artist_user = await _create_user(
        db_session, email="anirudh@example.com", display_name="Anirudh Ravichandran"
    )
    artist_client = _as(unauthenticated_client, artist_user)
    accept_response = await artist_client.post(
        ACCEPT_URL,
        json={"token": tagged["token"], "name_variants": ["Anirudh Ravichandran"], "handles": []},
    )
    assert accept_response.status_code == 200, accept_response.text

    feed = await artist_client.get(f"/api/v1/titles/{title_id}/mentions", params={"limit": 10})
    assert feed.status_code == 403, feed.text
    assert feed.json()["code"] == "PermissionDeniedError"
    assert ARTIST_SCOPED_FEED_MESSAGE in feed.text


async def test_stranger_still_gets_404_on_mentions_feed(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    """The regression this fix must not introduce: a caller with no relationship to the
    title at all -- not owner, not a shared grant of either kind -- still gets the same 404
    a missing title gets, not the artist's 403."""
    organization_id = await _create_organization(api_client)
    title_id = uuid.UUID(await _create_title(api_client, organization_id, _title_payload()))

    feed = await other_api_client.get(f"/api/v1/titles/{title_id}/mentions", params={"limit": 10})
    assert feed.status_code == 404, feed.text
    assert feed.json()["code"] == "ResourceNotFoundError"

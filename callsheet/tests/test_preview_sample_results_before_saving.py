"""Tests for E02-S03 — See real sample posts before committing setup, so I trust the
tracker from minute one.

Story: stories/E02-title-setup-identity-discovery/E02-S03-preview-sample-results-before-saving.md

The story has one Gherkin scenario ("Owner previews results and spots contamination
before saving"). Its Given/When/Then clauses, plus the Notes (which are testable
requirements in their own right), map to the sections below:

  - "Given: I have entered a title name, at least one anchor term, and at least one
    hashtag" -> the baseline precondition every test exercises via `_preview_payload`,
    which always carries a name, an anchor (`lead_cast`), and a hashtag.
  - "and Given: the setup screen offers a 'Preview matches' action" -> UI copy is out of
    scope; its backend-observable half is that `POST .../title-previews` exists and
    answers a well-formed request with a 200. Section 1.
  - "and Given: a preview runs a single capped search and returns at most 20 recent
    posts" -> Section 2: exactly one call to the search port, carrying the hard cap, and
    a misbehaving provider that returns more than the cap is still trimmed to it.
  - "and Given: each previewed post shows author, text, and why it matched" -> Section 3:
    every post in the response carries author fields, the original text untouched, and
    `matched_terms` explaining the inclusion.
  - "When: I run the preview" / "Then: I see the sample posts within seconds and can
    mark any of them 'not my title' before saving, which seeds the title's exclusion
    terms" -> Section 4: `candidate_exclusion_terms` on a contaminated post, and the full
    round trip of taking one of those terms into `TitleCreate.exclusions` on save.
  - Notes: "a preview that can run away on cost is a preview we cannot offer for free"
    -> Section 2 again (the cap). "Preview results are discarded, not stored as
    mentions" -> Section 5: a preview call creates no `Title` or `TitleTerm` rows.

Additional sections cover behaviour the task brief calls out explicitly: access control
(Section 6), input validation including the anchor rule and oversized payloads
(Section 7), the 503 path when no search adapter is configured (Section 8), and
multilingual/real-world content — Tamil script, code-mixed text, emoji, non-Latin
hashtags, and a platform-mislabelled language tag (Section 9).

Every assertion that could be satisfied by more than one failure path asserts on the
exact message or field, not just the status code, for the same reason
test_create_title_with_rich_identity.py does: a status-code-only check would still pass
even if the specific rule under test were deleted, so long as some other rule with the
same status code fired instead.

Sections 10-12 were added after a review round (`changes-requested`) found three
uncovered gaps, once `app/core/post_matching.py`'s word-boundary regex (which read
`#தமிழ்சினிமா` as `#தம்` — the Section 9 Tamil-hashtag failure this suite caught) was
replaced by `_is_word_character`, and `app/services/identity_rules.py` grew `ensure_fits`
as the one length rule the preview and the save now share:

  - Section 10: ZWJ/ZWNJ are word-internal in Indic scripts and must not fragment a
    hashtag, but a genuinely different word character (ZWSP) must still separate one
    word from the next.
  - Section 11: the NFKC-expansion length bound, applied on the preview path before the
    search runs — an identity set the save will reject must not spend a paid call first.
  - Section 12: `TitleService._ensure_exclusions_are_not_self_defeating`, which had no
    coverage anywhere — an exclusion may not name the title itself or anything already
    in its identity set, compared on the normalised form.

Section 13 was added after a second review round found the gap *between* Sections 10
and 12: Section 10 always used internally-consistent joiner placement on both sides of
each comparison, and Section 12 used only ASCII terms, so neither crossed a term
declared one way against the same word appearing spelled the other way. `normalize_term`
keeps ZWJ/ZWNJ (they carry meaning inside a word) but does not fold them for comparison,
so `#தமிழ்சினிமா` (declared without a joiner) and `#தமிழ்‌சினிமா` (typed or copied
with one) compared as different strings — the preview offered the studio's own hashtag
back as contamination, missed the true match entirely, and the self-exclusion guard let
the resulting exclusion through. The fix adds `joiner_folded`, a comparison-only view
with ZWJ/ZWNJ stripped, applied everywhere two terms are compared for sameness: matching,
suggestion, the self-exclusion guard, and identity-set dedupe. Storage and display forms
are untouched — only comparisons fold.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_preview_search
from app.db.session import get_db_session
from app.main import create_app
from app.models import Title, TitleTerm, User
from app.models.title import (
    MIN_UNANCHORED_NAME_LENGTH,
    TITLE_NAME_MAX_LENGTH,
    TITLE_TERM_MAX_LENGTH,
)
from app.schemas.title import MAX_TERMS_PER_FIELD
from app.services.identity_rules import TOO_LONG_MESSAGE, UNANCHORED_NAME_MESSAGE
from app.services.preview_search import (
    PREVIEW_PLATFORM,
    PREVIEW_POST_LIMIT,
    PREVIEW_UNAVAILABLE_MESSAGE,
    PreviewSearch,
    SamplePost,
)
from app.services.title_preview_service import EMPTY_NAME_MESSAGE, NOT_AN_OWNER_MESSAGE
from app.services.title_service import SELF_EXCLUDING_TERM_MESSAGE

ORGANIZATIONS_URL = "/api/v1/organizations"

SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}

FORMATTED_UNANCHORED_NAME_MESSAGE = UNANCHORED_NAME_MESSAGE.format(
    minimum=MIN_UNANCHORED_NAME_LENGTH
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


class FakeSearch(PreviewSearch):
    """Stands in for the E03 Monid adapter.

    Records every call it receives (query, limit) so tests can assert the "single
    capped search" rule directly, and hands back whatever a test configured — including
    more posts than the cap allows, to exercise the provider-misbehaves path.
    """

    def __init__(self, posts: list[SamplePost] | None = None) -> None:
        self.posts: list[SamplePost] = list(posts or [])
        self.calls: list[tuple[str, int]] = []

    async def search_recent(self, query: str, *, limit: int) -> list[SamplePost]:
        self.calls.append((query, limit))
        return self.posts


@pytest.fixture
def fake_search() -> FakeSearch:
    return FakeSearch()


@pytest.fixture
async def preview_client(
    db_session: AsyncSession, pilot_user: User, fake_search: FakeSearch
) -> AsyncIterator[AsyncClient]:
    """The same shape as `api_client`, but with the preview search seam bound to
    `fake_search` instead of the unconfigured default — the override pattern
    `app/api/deps.py` documents by analogy to `get_invitation_notifier`.
    """
    app = create_app()

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_preview_search] = lambda: fake_search

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.headers["X-User-Id"] = str(pilot_user.id)
        yield client

    app.dependency_overrides.clear()


def _preview_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/title-previews"


def _titles_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/titles"


async def _create_organization(client: AsyncClient, payload: dict = SUN_PICTURES_PAYLOAD) -> str:
    response = await client.post(ORGANIZATIONS_URL, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _invite(
    client: AsyncClient, organization_id: str, email: str, role: str = "viewer"
) -> dict:
    response = await client.post(
        f"{ORGANIZATIONS_URL}/{organization_id}/invitations",
        json={"email": email, "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _accept(client: AsyncClient, token: str) -> None:
    response = await client.post("/api/v1/invitations/accept", json={"token": token})
    assert response.status_code == 204, response.text


async def _make_viewer(
    owner_client: AsyncClient, viewer_client: AsyncClient, organization_id: str, email: str
) -> None:
    invitation = await _invite(owner_client, organization_id, email, "viewer")
    await _accept(viewer_client, invitation["token"])


def _preview_payload(**overrides: object) -> dict:
    """The Given clause's own baseline: a name, an anchor term, and a hashtag."""
    payload: dict = {
        "name": "Vaaranam",
        "aliases": [],
        "hashtags": ["#Vaaranam"],
        "lead_cast": ["Suriya"],
        "directors": [],
        "music_directors": [],
    }
    payload.update(overrides)
    return payload


def _title_create_payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "Vaaranam",
        "release_date": "2026-09-11",
        "aliases": [],
        "hashtags": ["#Vaaranam"],
        "lead_cast": ["Suriya"],
        "directors": [],
        "music_directors": [],
        "exclusions": [],
    }
    payload.update(overrides)
    return payload


async def _preview(client: AsyncClient, organization_id: str, **overrides: object):
    return await client.post(_preview_url(organization_id), json=_preview_payload(**overrides))


async def _preview_ok(client: AsyncClient, organization_id: str, **overrides: object) -> dict:
    response = await _preview(client, organization_id, **overrides)
    assert response.status_code == 200, response.text
    return response.json()


def _sample_post(index: int, **overrides: object) -> SamplePost:
    defaults: dict = dict(
        external_id=f"post-{index}",
        author_handle=f"@fan{index}",
        author_display_name=f"Fan {index}",
        text="Vaaranam mass! #Vaaranam",
        posted_at=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        permalink=f"https://x.com/fan{index}/status/{index}",
        platform_reported_language="en",
    )
    defaults.update(overrides)
    return SamplePost(**defaults)


# ---------------------------------------------------------------------------
# Section 1 — Given: the setup screen offers a "Preview matches" action. Backend half:
# the endpoint exists and answers a well-formed request with real sample data.
# ---------------------------------------------------------------------------


async def test_preview_endpoint_returns_200_with_the_sample(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0)]

    response = await _preview(preview_client, organization_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["platform"] == PREVIEW_PLATFORM
    assert len(body["posts"]) == 1


async def test_preview_query_is_the_single_anchored_phrase(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """The query the preview actually ran is reported back, so the studio can see what
    was searched — and it is the anchored form (`build_anchored_query`), the shape the
    live run measured, not the bare name."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = []

    body = await _preview_ok(
        preview_client, organization_id, name="Vaaranam", lead_cast=["Suriya"], hashtags=[]
    )

    assert body["query"] == '"Suriya Vaaranam"'


# ---------------------------------------------------------------------------
# Section 2 — Given: a preview runs a single capped search and returns at most 20
# recent posts (Notes: a preview that can run away on cost cannot be offered for free).
# ---------------------------------------------------------------------------


async def test_preview_calls_search_exactly_once_carrying_the_hard_cap(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0), _sample_post(1)]

    await _preview_ok(preview_client, organization_id)

    assert len(fake_search.calls) == 1
    _query, limit = fake_search.calls[0]
    assert limit == PREVIEW_POST_LIMIT == 20


async def test_response_post_limit_field_reports_the_hard_cap(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    organization_id = await _create_organization(preview_client)
    fake_search.posts = []

    body = await _preview_ok(preview_client, organization_id)

    assert body["post_limit"] == 20


async def test_a_provider_that_misbehaves_and_returns_more_than_20_posts_is_still_capped(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """A provider ignoring `limit` and returning 25 posts must not widen the sample the
    studio receives — the service re-applies the cap on the way out, and it still made
    only the one call."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(i) for i in range(25)]

    body = await _preview_ok(preview_client, organization_id)

    assert len(body["posts"]) == 20
    assert len(fake_search.calls) == 1
    # The cap keeps the first 20 in the order the provider returned them.
    assert [post["id"] for post in body["posts"]] == [f"post-{i}" for i in range(20)]


async def test_exactly_20_posts_from_the_provider_are_all_returned(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """Boundary check from the other side: a provider that respects the cap exactly is
    not short-changed by an off-by-one in the trim."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(i) for i in range(20)]

    body = await _preview_ok(preview_client, organization_id)

    assert len(body["posts"]) == 20


async def test_duplicate_external_ids_from_the_provider_are_deduplicated_before_the_cap(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """A repeated id is one post, twice — not two posts. First occurrence wins."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [
        _sample_post(0, text="First copy"),
        _sample_post(0, text="Second copy, same id"),
        _sample_post(1),
    ]

    body = await _preview_ok(preview_client, organization_id)

    assert len(body["posts"]) == 2
    assert body["posts"][0]["id"] == "post-0"
    assert body["posts"][0]["text"] == "First copy"


# ---------------------------------------------------------------------------
# Section 3 — Given: each previewed post shows author, text, and why it matched.
# ---------------------------------------------------------------------------


async def test_each_previewed_post_carries_author_text_and_why_it_matched(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """The post carrying the story's own worked example: a hashtag that matches the
    identity set (#DC) beside one that does not (#DareDevil) — a contamination
    candidate the studio can see and act on."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [
        _sample_post(
            0,
            author_handle="@dc_stan_007",
            author_display_name="DC Stan",
            text="Absolute banger. #DC #DareDevil",
        )
    ]

    body = await _preview_ok(
        preview_client,
        organization_id,
        name="DC",
        hashtags=["#DC"],
        directors=["Zack Snyder"],
    )

    post = body["posts"][0]
    assert post["author_handle"] == "@dc_stan_007"
    assert post["author_display_name"] == "DC Stan"
    assert post["text"] == "Absolute banger. #DC #DareDevil"
    assert "DC" in post["matched_terms"]
    assert post["candidate_exclusion_terms"] == ["#DareDevil"]


async def test_matching_evaluates_author_fields_too_not_only_text(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """The evidence for "why it matched" is drawn from the whole post, not just the
    body text — a cast name appearing only in the author's display name still counts."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [
        _sample_post(
            0,
            author_handle="@suriya_fan",
            author_display_name="Suriya Army",
            text="Can't wait for this one!",
        )
    ]

    body = await _preview_ok(preview_client, organization_id, name="Vaaranam", lead_cast=["Suriya"])

    assert "Suriya" in body["posts"][0]["matched_terms"]


async def test_post_with_no_identity_overlap_reports_empty_matched_terms(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [
        _sample_post(0, text="Completely unrelated content about something else entirely")
    ]

    body = await _preview_ok(preview_client, organization_id)

    assert body["posts"][0]["matched_terms"] == []


# ---------------------------------------------------------------------------
# Section 4 — When/Then: mark a post "not my title" before saving, which seeds the
# title's exclusion terms — the round trip from preview to a saved title.
# ---------------------------------------------------------------------------


async def test_marking_a_post_not_my_title_round_trips_into_the_saved_titles_exclusions(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """The full story arc in one test: preview surfaces a contaminated post, the studio
    marks it "not my title" (client picks up `candidate_exclusion_terms`), and saving
    the title with that term in `exclusions` persists it as an exclusion term."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [
        _sample_post(0, text="Absolute banger. #DC #DareDevil"),
    ]

    preview = await _preview_ok(
        preview_client, organization_id, name="DC", hashtags=["#DC"], directors=["Zack Snyder"]
    )
    contamination = preview["posts"][0]["candidate_exclusion_terms"]
    assert contamination == ["#DareDevil"]

    created = await preview_client.post(
        _titles_url(organization_id),
        json=_title_create_payload(
            name="DC",
            hashtags=["#DC"],
            directors=["Zack Snyder"],
            exclusions=contamination,
        ),
    )
    assert created.status_code == 201, created.text
    saved_title = created.json()

    assert "daredevil" in saved_title["excluded_terms"]


async def test_exclusions_seeded_from_the_preview_never_leak_into_collection_terms(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text="Absolute banger. #DC #DareDevil")]

    preview = await _preview_ok(
        preview_client, organization_id, name="DC", hashtags=["#DC"], directors=["Zack Snyder"]
    )
    contamination = preview["posts"][0]["candidate_exclusion_terms"]

    created = await preview_client.post(
        _titles_url(organization_id),
        json=_title_create_payload(
            name="DC",
            hashtags=["#DC"],
            directors=["Zack Snyder"],
            exclusions=contamination,
        ),
    )
    assert created.status_code == 201, created.text
    saved_title = created.json()

    assert "daredevil" not in saved_title["collection_terms"]
    assert "dc" in saved_title["collection_terms"]
    assert "zack snyder" in saved_title["collection_terms"]


async def test_candidate_exclusion_terms_exclude_hashtags_already_in_the_identity_set(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """The identity set's own hashtag must never be offered back as a candidate
    exclusion — only the contaminating extra hashtag is a real candidate."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text="#Vaaranam vera level #RandomOtherTag")]

    body = await _preview_ok(preview_client, organization_id)

    assert body["posts"][0]["candidate_exclusion_terms"] == ["#RandomOtherTag"]


async def test_a_clean_post_with_no_stray_hashtags_has_no_exclusion_candidates(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text="#Vaaranam looks great, can't wait!")]

    body = await _preview_ok(preview_client, organization_id)

    assert body["posts"][0]["candidate_exclusion_terms"] == []


# ---------------------------------------------------------------------------
# Section 5 — Notes: preview results are discarded, not stored. A preview call must
# create no Title and no TitleTerm rows.
# ---------------------------------------------------------------------------


async def test_preview_persists_no_title_row(
    preview_client: AsyncClient, fake_search: FakeSearch, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0), _sample_post(1)]

    await _preview_ok(preview_client, organization_id)

    titles = (await db_session.execute(select(Title))).scalars().all()
    assert titles == []


async def test_preview_persists_no_title_term_rows(
    preview_client: AsyncClient, fake_search: FakeSearch, db_session: AsyncSession
) -> None:
    """Even though the preview computed exclusion candidates, nothing about them — or
    about the matched identity terms — is written anywhere."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text="Absolute banger. #DC #DareDevil")]

    await _preview_ok(
        preview_client, organization_id, name="DC", hashtags=["#DC"], directors=["Zack Snyder"]
    )

    terms = (await db_session.execute(select(TitleTerm))).scalars().all()
    assert terms == []


async def test_repeated_previews_of_the_same_identity_set_persist_nothing_across_calls(
    preview_client: AsyncClient, fake_search: FakeSearch, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0)]

    await _preview_ok(preview_client, organization_id)
    await _preview_ok(preview_client, organization_id)
    await _preview_ok(preview_client, organization_id)

    assert len(fake_search.calls) == 3
    titles = (await db_session.execute(select(Title))).scalars().all()
    assert titles == []


# ---------------------------------------------------------------------------
# Section 6 — Access control: non-member, viewer (non-owner), unauthenticated.
# Preview is owner-gated the same way creating a title is (it is part of setting one
# up), so access-denied requests never reach the search port at all.
# ---------------------------------------------------------------------------


async def test_non_member_previewing_gets_the_same_not_found_a_missing_org_would(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)

    response = await other_api_client.post(
        _preview_url(organization_id), json=_preview_payload()
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_viewer_non_owner_cannot_preview(
    api_client: AsyncClient, other_api_client: AsyncClient, other_pilot_user: User
) -> None:
    """A viewer can see the organization (they are a member), so the refusal is an
    honest 403, not a 404 — same shape as the create-title access rule."""
    organization_id = await _create_organization(api_client)
    await _make_viewer(api_client, other_api_client, organization_id, other_pilot_user.email)

    response = await other_api_client.post(
        _preview_url(organization_id), json=_preview_payload()
    )

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "PermissionDeniedError"
    assert body["message"] == NOT_AN_OWNER_MESSAGE


async def test_unauthenticated_cannot_preview(
    api_client: AsyncClient, unauthenticated_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)

    response = await unauthenticated_client.post(
        _preview_url(organization_id), json=_preview_payload()
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_non_member_preview_attempt_persists_nothing_either(
    api_client: AsyncClient, other_api_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)

    await other_api_client.post(_preview_url(organization_id), json=_preview_payload())

    titles = (await db_session.execute(select(Title))).scalars().all()
    assert titles == []


# ---------------------------------------------------------------------------
# Section 7 — Validation: empty/invisible-only name, an identity set failing the
# anchor rule, and oversized payloads. The preview enforces the same rule the save
# would, first — so a preview never shows a sample the save would then refuse.
# ---------------------------------------------------------------------------


async def test_empty_name_is_refused_by_pydantic(preview_client: AsyncClient) -> None:
    organization_id = await _create_organization(preview_client)

    response = await _preview(preview_client, organization_id, name="")

    assert response.status_code == 422


@pytest.mark.parametrize(
    "invisible_name",
    ["   ", "​​​", "‌‍", "﻿"],
    ids=["whitespace_only", "zwsp_run", "zwnj_zwj", "bom"],
)
async def test_invisible_only_name_is_refused_as_an_empty_name(
    preview_client: AsyncClient, invisible_name: str
) -> None:
    """Passes pydantic's `min_length=1` (these are real characters, just invisible
    ones), so the rejection must come from the service's own content check —
    `EMPTY_NAME_MESSAGE`, distinct from the anchor-rule message below."""
    organization_id = await _create_organization(preview_client)

    response = await _preview(preview_client, organization_id, name=invisible_name)

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == EMPTY_NAME_MESSAGE


async def test_identity_set_failing_the_anchor_rule_is_refused(
    preview_client: AsyncClient,
) -> None:
    """The story's own franchise-collision example: a bare two-letter name with no
    cast or crew attached — a hashtag alone does not rescue it. Previewing must refuse
    this exactly as saving would, and for the same reason."""
    organization_id = await _create_organization(preview_client)

    response = await _preview(
        preview_client,
        organization_id,
        name="DC",
        hashtags=["#DC"],
        lead_cast=[],
        directors=[],
        music_directors=[],
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == FORMATTED_UNANCHORED_NAME_MESSAGE


async def test_anchor_rule_failure_makes_no_search_call(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """An identity set that cannot be saved must not spend the search either — the
    anchor rule is checked before the single capped call is made."""
    organization_id = await _create_organization(preview_client)

    await _preview(
        preview_client,
        organization_id,
        name="DC",
        hashtags=["#DC"],
        lead_cast=[],
        directors=[],
        music_directors=[],
    )

    assert fake_search.calls == []


async def test_identity_set_with_a_cast_anchor_and_a_short_name_is_accepted(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """The other side of the anchor-rule boundary: the same short name succeeds once a
    real cast/crew term is present."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = []

    response = await _preview(
        preview_client, organization_id, name="DC", hashtags=["#DC"], lead_cast=["Ezra Miller"]
    )

    assert response.status_code == 200, response.text


async def test_oversized_name_is_refused_by_pydantic(preview_client: AsyncClient) -> None:
    organization_id = await _create_organization(preview_client)
    overlong_name = "a" * (TITLE_NAME_MAX_LENGTH + 1)

    response = await _preview(preview_client, organization_id, name=overlong_name)

    assert response.status_code == 422, response.text
    assert "detail" in response.json()


async def test_oversized_term_in_a_field_is_refused_by_pydantic(
    preview_client: AsyncClient,
) -> None:
    """Mirrors the E02-S01 Fix A regression guard: `TitlePreviewRequest` reuses
    `TermList`, whose per-item `max_length` must reject an overlong term before it
    ever reaches the service, not just an overlong list."""
    organization_id = await _create_organization(preview_client)
    overlong_term = "a" * (TITLE_TERM_MAX_LENGTH + 1)

    response = await _preview(preview_client, organization_id, aliases=[overlong_term])

    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert any(
        error["type"] == "string_too_long" and error["loc"][:2] == ["body", "aliases"]
        for error in errors
    )


async def test_more_than_max_terms_in_a_field_is_refused_by_pydantic(
    preview_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(preview_client)
    too_many_hashtags = [f"#tag{i}" for i in range(MAX_TERMS_PER_FIELD + 1)]

    response = await _preview(preview_client, organization_id, hashtags=too_many_hashtags)

    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert any(
        error["type"] == "too_long" and error["loc"][:2] == ["body", "hashtags"]
        for error in errors
    )


async def test_invalid_payload_makes_no_search_call_and_persists_nothing(
    preview_client: AsyncClient, fake_search: FakeSearch, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(preview_client)

    await _preview(preview_client, organization_id, name="   ")

    assert fake_search.calls == []
    titles = (await db_session.execute(select(Title))).scalars().all()
    assert titles == []


# ---------------------------------------------------------------------------
# Section 8 — the 503 path: no search adapter configured (the default binding).
# ---------------------------------------------------------------------------


async def test_preview_with_no_configured_adapter_returns_503(api_client: AsyncClient) -> None:
    """`api_client` uses the real dependency graph, where `get_preview_search` still
    defaults to `UnconfiguredPreviewSearch` — this is what a fresh deployment answers
    with before E03 wires up a real adapter."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(_preview_url(organization_id), json=_preview_payload())

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["code"] == "ServiceUnavailableError"
    assert body["message"] == PREVIEW_UNAVAILABLE_MESSAGE


async def test_unconfigured_adapter_path_persists_nothing(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)

    await api_client.post(_preview_url(organization_id), json=_preview_payload())

    titles = (await db_session.execute(select(Title))).scalars().all()
    assert titles == []


async def test_unconfigured_adapter_still_enforces_access_control_first(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    """A non-member must not learn anything about the search being unconfigured — the
    membership check runs first regardless of which adapter is bound."""
    organization_id = await _create_organization(api_client)

    response = await other_api_client.post(
        _preview_url(organization_id), json=_preview_payload()
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


# ---------------------------------------------------------------------------
# Section 9 — Multilingual / real-world content: Tamil script, code-mixed Latin-script
# text, emoji, hashtags in non-Latin scripts, and a post whose platform-reported
# language tag is wrong.
# ---------------------------------------------------------------------------


async def test_pure_tamil_script_post_text_round_trips_untouched(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    tamil_text = "இது ஒரு அற்புதமான படம் #வாரணம்"
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text=tamil_text, platform_reported_language="ta")]

    body = await _preview_ok(preview_client, organization_id)

    assert body["posts"][0]["text"] == tamil_text
    # A Latin-script identity set does not spuriously match unrelated Tamil content —
    # no crash, no accidental match.
    assert body["posts"][0]["matched_terms"] == []


async def test_code_mixed_latin_script_text_still_matches_identity_terms(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """Tanglish (Tamil written in Latin script, mixed with English) is exactly the
    kind of organic content this preview exists to sample. Matching is casefolded, so
    the identity terms are found regardless of how the studio capitalised them."""
    code_mixed_text = "suriya mass in vaaranam padam, thala fans rocking! semma fdfs"
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text=code_mixed_text)]

    body = await _preview_ok(preview_client, organization_id, name="Vaaranam", lead_cast=["Suriya"])

    matched = set(body["posts"][0]["matched_terms"])
    assert {"Vaaranam", "Suriya"} <= matched


async def test_emoji_and_hashtag_heavy_text_round_trips_without_error(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    emoji_text = "🔥🔥 #Vaaranam vera level padam 🎬🙌 must watch!!"
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text=emoji_text)]

    body = await _preview_ok(preview_client, organization_id)

    assert body["posts"][0]["text"] == emoji_text
    assert "Vaaranam" in body["posts"][0]["matched_terms"]


async def test_hashtags_in_non_latin_scripts_are_offered_as_exclusion_candidates(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """`find_matching_terms`/`suggest_exclusion_terms` use Unicode-aware `\\w`
    matching, so a hashtag in Tamil script must be found and offered as a candidate
    exclusion exactly like a Latin-script one would be."""
    text_with_tamil_hashtag = "Vaaranam semma #Vaaranam #தமிழ்சினிமா"
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text=text_with_tamil_hashtag)]

    body = await _preview_ok(preview_client, organization_id)

    assert "#தமிழ்சினிமா" in body["posts"][0]["candidate_exclusion_terms"]
    # The identity set's own hashtag must not also show up as a candidate.
    assert "#Vaaranam" not in body["posts"][0]["candidate_exclusion_terms"]


async def test_post_with_a_wrong_platform_reported_language_tag_passes_it_through_unverified(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """`platform_reported_language` is a claim, not a fact (per the field's own
    docstring: roughly half the non-English content in the live sample was mislabelled
    by the platform). The preview must never attempt to correct or filter on it — it is
    passed straight through exactly as the "adapter" reported it, wrong or not."""
    tamil_text = "இது ஒரு அற்புதமான படம், நிச்சயம் பாருங்கள்"
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [
        # The platform claims this is English; it plainly is not.
        _sample_post(0, text=tamil_text, platform_reported_language="en")
    ]

    body = await _preview_ok(preview_client, organization_id)

    assert body["posts"][0]["platform_reported_language"] == "en"
    assert body["posts"][0]["text"] == tamil_text


async def test_missing_platform_reported_language_is_passed_through_as_null(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, platform_reported_language=None)]

    body = await _preview_ok(preview_client, organization_id)

    assert body["posts"][0]["platform_reported_language"] is None


# ---------------------------------------------------------------------------
# Section 10 — ZWJ/ZWNJ boundary behaviour. Both sit inside Indic-script words,
# controlling whether adjacent consonants form a conjunct, so `_is_word_character`
# treats them as word characters. ZWSP is a genuinely different character (Cf, but not
# a joiner) and must still separate words. This is the regression suite for the fix
# that replaced the `\w+` regex which produced Section 9's Tamil-hashtag failure.
# ---------------------------------------------------------------------------


async def test_hashtag_containing_a_zwnj_is_offered_as_a_candidate_exclusion_term_whole(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """ZWNJ (U+200C) sits inside a word in Tamil, separating two letters that must not
    form a conjunct. `#தமிழ்<ZWNJ>சினிமா` is one word wearing a joiner, not two words
    glued together by an invisible character — the candidate exclusion offered back
    must be the whole hashtag, not truncated at the joiner the way the old `\\w+` regex
    truncated it at a vowel sign (Section 9)."""
    zwnj_hashtag_body = "தமிழ்‌சினிமா"
    text = f"Vaaranam semma #{zwnj_hashtag_body} padam da"
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text=text)]

    body = await _preview_ok(preview_client, organization_id)

    assert f"#{zwnj_hashtag_body}" in body["posts"][0]["candidate_exclusion_terms"]


async def test_short_identity_term_does_not_falsely_match_inside_a_zwj_joined_compound(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """ZWJ (U+200D) joins the same way ZWNJ does. A short alias `தமிழ்` sitting inside
    `தமிழ்<ZWJ>சினிமா` is not a standalone occurrence of that alias — it is one word made
    of two, and reporting it as "why this post matched" would be an invisible-character
    -dependent false positive. The same alias genuinely standing alone in a second post
    must still match, proving the miss is caused by the joiner and not by some unrelated
    breakage in matching itself."""
    joined_word = "தமிழ்‍சினிமா"
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [
        _sample_post(0, text=f"இது {joined_word} படம்"),
        _sample_post(1, text="தமிழ் திரைப்படம் அருமை"),
    ]

    body = await _preview_ok(
        preview_client,
        organization_id,
        name="Vaaranam",
        hashtags=["#Vaaranam"],
        aliases=["தமிழ்"],
    )

    joined_post, standalone_post = body["posts"]
    assert "தமிழ்" not in joined_post["matched_terms"]
    assert "தமிழ்" in standalone_post["matched_terms"]


async def test_zero_width_space_still_separates_words_inside_a_hashtag(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """ZWSP (U+200B) is category Cf, same as ZWJ/ZWNJ, but it is not one of the two
    joining characters carved out for Indic conjuncts — it genuinely separates one word
    from the next. `#dc<ZWSP>marvel` must yield the hashtag `#dc`, not the run-together
    `#dcmarvel`, and `marvel` (no leading hash of its own) is not extracted as a hashtag
    at all."""
    text = "Excited for #dc​marvel news"
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text=text)]

    body = await _preview_ok(preview_client, organization_id)

    assert body["posts"][0]["candidate_exclusion_terms"] == ["#dc"]


# ---------------------------------------------------------------------------
# Section 11 — The NFKC-expansion length bound on the preview path. A value that clears
# Pydantic's raw `max_length` can still expand past `ensure_fits`'s limit once ligatures
# are normalised to their standard form, and the preview must catch this *before*
# spending the one paid search call — an identity set the save is going to reject is not
# worth a call the studio has not paid for.
# ---------------------------------------------------------------------------


async def test_nfkc_expanded_name_is_refused_before_the_search_runs(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """250 copies of the ligature 'ﬁ' clear Pydantic's raw `max_length=300` on `name`
    (250 <= 300), but NFKC normalisation — applied by `clean_display_value` before
    anything else sees the name — expands each into 'fi', giving 500 characters, well
    past `TITLE_NAME_MAX_LENGTH`. The point of this test is the zero: the search must
    never run on an identity set the save is going to refuse."""
    ligature_name = "ﬁ" * 250
    assert len(ligature_name) == 250
    organization_id = await _create_organization(preview_client)

    response = await _preview(preview_client, organization_id, name=ligature_name)

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == TOO_LONG_MESSAGE.format(
        subject="This title name", limit=TITLE_NAME_MAX_LENGTH
    )
    assert fake_search.calls == []


async def test_nfkc_expanded_identity_term_is_refused_before_the_search_runs(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """Same trap, on a term instead of the name: 250 copies of 'ﬁ' in `aliases` clear
    the per-item `TermList` cap (300) raw, then expand to 500 characters once
    normalised — over `TITLE_TERM_MAX_LENGTH`. Refused before the search runs, for the
    same cost reason."""
    ligature_term = "ﬁ" * 250
    organization_id = await _create_organization(preview_client)

    response = await _preview(preview_client, organization_id, aliases=[ligature_term])

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == TOO_LONG_MESSAGE.format(
        subject="An identity term", limit=TITLE_TERM_MAX_LENGTH
    )
    assert fake_search.calls == []


async def test_nfkc_expanded_name_refusal_message_matches_the_save_path_exactly(
    preview_client: AsyncClient,
) -> None:
    """Not just "a 422 with some message" — literally the same message text the save
    gives for the identical input. `ensure_fits`/`TOO_LONG_MESSAGE` moved into
    `identity_rules` for exactly this reason: one rule, shared by both callers, so they
    can never drift apart."""
    ligature_name = "ﬁ" * 250
    organization_id = await _create_organization(preview_client)

    preview_response = await _preview(preview_client, organization_id, name=ligature_name)
    save_response = await preview_client.post(
        _titles_url(organization_id),
        json=_title_create_payload(name=ligature_name),
    )

    assert preview_response.status_code == 422, preview_response.text
    assert save_response.status_code == 422, save_response.text
    assert preview_response.json()["message"] == save_response.json()["message"]


# ---------------------------------------------------------------------------
# Section 12 — TitleService._ensure_exclusions_are_not_self_defeating. Not previously
# covered anywhere: an exclusion may not name the title itself or anything already in
# its identity set, compared on the normalised form, because that exclusion would
# disqualify the title's own posts and collect nothing while looking configured. This
# is the rule that guards the far end of the E02-S03 round trip (Section 4) — a
# mis-click on "not my title" must be refused at the door, not silently accepted.
# ---------------------------------------------------------------------------


async def test_exclusion_equal_to_the_titles_own_name_is_refused(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_title_create_payload(
            name="Vaaranam", hashtags=[], lead_cast=[], exclusions=["Vaaranam"]
        ),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == SELF_EXCLUDING_TERM_MESSAGE.format(term="Vaaranam")


@pytest.mark.parametrize(
    "field_name,term_value,exclusion_value",
    [
        ("hashtags", "#DC", "dc"),
        ("hashtags", "#DC", "DC"),
        ("hashtags", "#DC", "#dc"),
        ("aliases", "VA", "va"),
        ("lead_cast", "Suriya", "SURIYA"),
    ],
    ids=[
        "hashtag_hash_stripped_lowercase",
        "hashtag_hash_stripped_uppercase",
        "hashtag_same_hash_lowercase",
        "alias_case_folded",
        "cast_case_folded",
    ],
)
async def test_exclusion_colliding_with_an_identity_term_on_the_normalized_form_is_refused(
    api_client: AsyncClient, field_name: str, term_value: str, exclusion_value: str
) -> None:
    """The self-defeat guard compares normalised forms, not literal strings — '#DC',
    'dc', and 'DC' must all collide with each other regardless of which field the
    positive term lives in (hashtag, alias, or cast)."""
    organization_id = await _create_organization(api_client)
    overrides: dict = {
        "name": "Vaaranam",
        "hashtags": [],
        "lead_cast": [],
        "exclusions": [exclusion_value],
    }
    overrides[field_name] = [term_value]

    response = await api_client.post(
        _titles_url(organization_id), json=_title_create_payload(**overrides)
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == SELF_EXCLUDING_TERM_MESSAGE.format(term=exclusion_value)


async def test_title_with_only_unrelated_exclusions_is_created_normally(
    api_client: AsyncClient,
) -> None:
    """The guard only refuses a *colliding* exclusion — an exclusion naming something
    genuinely outside the identity set must not block creation, and the title's own
    name must still be exactly what it always is: part of `collection_terms`."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_title_create_payload(
            name="Vaaranam",
            hashtags=["#Vaaranam"],
            lead_cast=[],
            exclusions=["#RandomOtherFranchise"],
        ),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert "randomotherfranchise" in body["excluded_terms"]
    assert "vaaranam" in body["collection_terms"]
    assert "randomotherfranchise" not in body["collection_terms"]


# ---------------------------------------------------------------------------
# Section 13 — Cross-area coverage: a term declared one way (with or without a ZWJ/ZWNJ
# joiner) against the same word appearing in a post spelled the other way. This is the
# gap between Section 10 (always internally consistent joiner placement) and Section 12
# (ASCII only) that let `#தமிழ்சினிமா` declared bare and `#தமிழ்<ZWNJ>சினிமா` typed
# into a post compare as different strings before `joiner_folded` existed.
# ---------------------------------------------------------------------------

_TAMIL_HASHTAG_NO_JOINER = "#தமிழ்சினிமா"
_TAMIL_HASHTAG_WITH_ZWNJ = "#தமிழ்‌சினிமா"
_TAMIL_WORD_NO_JOINER = "தமிழ்சினிமா"
_TAMIL_WORD_WITH_ZWNJ = "தமிழ்‌சினிமா"


async def test_hashtag_declared_without_a_joiner_is_matched_and_not_offered_when_the_post_has_one(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """The studio declared `#தமிழ்சினிமா` with no joiner. The post spells the same word
    with an embedded ZWNJ. The two must fold to the same comparable term: it is reported
    as a match (why this post is in the sample), and it is never offered back as a
    candidate exclusion — that would be the preview flagging the studio's own declared
    hashtag as contamination."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text=f"இது {_TAMIL_HASHTAG_WITH_ZWNJ} படம்")]

    body = await _preview_ok(preview_client, organization_id, hashtags=[_TAMIL_HASHTAG_NO_JOINER])

    post = body["posts"][0]
    assert _TAMIL_HASHTAG_NO_JOINER in post["matched_terms"]
    assert post["candidate_exclusion_terms"] == []


async def test_hashtag_declared_with_a_joiner_is_matched_and_not_offered_when_the_post_has_none(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """The reverse direction: the studio's own declared hashtag carries the joiner, and
    the post spells the word without one. Still the same word, still a match, still
    never offered back as contamination."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text=f"இது {_TAMIL_HASHTAG_NO_JOINER} படம்")]

    body = await _preview_ok(
        preview_client, organization_id, hashtags=[_TAMIL_HASHTAG_WITH_ZWNJ]
    )

    post = body["posts"][0]
    assert _TAMIL_HASHTAG_WITH_ZWNJ in post["matched_terms"]
    assert post["candidate_exclusion_terms"] == []


async def test_self_exclusion_guard_refuses_a_hashtag_that_only_collides_after_joiner_folding(
    api_client: AsyncClient,
) -> None:
    """The exact defect reproduced: the studio declares `#தமிழ்சினிமா` with no joiner,
    then (from a preview candidate that came out of a post spelling it with one) tries
    to exclude `#தமிழ்<ZWNJ>சினிமா`. Literal comparison would miss the collision and
    let this through, silently disqualifying the title's own posts. It must be refused."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_title_create_payload(
            name="Vaaranam",
            hashtags=[_TAMIL_HASHTAG_NO_JOINER],
            lead_cast=[],
            exclusions=[_TAMIL_HASHTAG_WITH_ZWNJ],
        ),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == SELF_EXCLUDING_TERM_MESSAGE.format(term=_TAMIL_HASHTAG_WITH_ZWNJ)


async def test_self_exclusion_guard_refuses_a_name_that_only_collides_after_joiner_folding(
    api_client: AsyncClient,
) -> None:
    """Same collision, against the title NAME instead of a hashtag: the name is declared
    without a joiner, the exclusion carries one, and the guard must still see them as the
    same word."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_title_create_payload(
            name=_TAMIL_WORD_NO_JOINER,
            hashtags=[],
            lead_cast=[],
            exclusions=[_TAMIL_WORD_WITH_ZWNJ],
        ),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == SELF_EXCLUDING_TERM_MESSAGE.format(term=_TAMIL_WORD_WITH_ZWNJ)


async def test_hashtag_submitted_with_and_without_a_joiner_dedupes_to_one_stored_term(
    api_client: AsyncClient,
) -> None:
    """Two spellings of one word are one term. Submitting the same hashtag twice —
    once bare, once with an embedded ZWNJ — must store exactly one `TitleTerm`, keeping
    the first spelling typed."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_title_create_payload(
            name="Vaaranam",
            hashtags=[_TAMIL_HASHTAG_NO_JOINER, _TAMIL_HASHTAG_WITH_ZWNJ],
            lead_cast=[],
        ),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    hashtag_terms = [term for term in body["terms"] if term["term_type"] == "hashtag"]
    assert len(hashtag_terms) == 1
    assert hashtag_terms[0]["value"] == _TAMIL_HASHTAG_NO_JOINER  # first spelling typed


# --- Over-folding guards: the fold must not weaken word boundaries it has nothing to
# do with, and must not touch scripts/characters it was never meant to touch. ---


async def test_zero_width_space_still_separates_a_hashtag_after_the_joiner_folding_fix(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """ZWSP (U+200B) is not one of the two folded joiners — `joiner_folded` must not
    have widened its reach to swallow it too. `#dc<ZWSP>marvel` must still yield only
    `#dc`, exactly as it did before this fix (Section 10)."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text="Excited for #dc​marvel news")]

    body = await _preview_ok(preview_client, organization_id)

    assert body["posts"][0]["candidate_exclusion_terms"] == ["#dc"]


async def test_short_hashtag_still_does_not_falsely_match_a_longer_zwj_joined_compound(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """The declared hashtag `#தமிழ்` is a genuine prefix of the longer, unrelated
    compound word `தமிழ்<ZWJ>சினிமா` in the post. Folding the joiner out must not make
    these the same word — the short term must not match, and the longer compound must
    still be offered as its own, distinct exclusion candidate, joiner intact."""
    organization_id = await _create_organization(preview_client)
    joined_compound_hashtag = f"#{_TAMIL_WORD_NO_JOINER[:5]}‍{_TAMIL_WORD_NO_JOINER[5:]}"
    fake_search.posts = [_sample_post(0, text=f"இது {joined_compound_hashtag} படம்")]

    body = await _preview_ok(preview_client, organization_id, hashtags=["#தமிழ்"])

    post = body["posts"][0]
    assert "#தமிழ்" not in post["matched_terms"]
    assert post["candidate_exclusion_terms"] == [joined_compound_hashtag]


async def test_plain_latin_term_still_does_not_match_as_a_substring_of_an_unrelated_word(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """`DC` must not match inside `abcdcx` — ordinary whole-word containment, unrelated
    to joiners, and unaffected by the fold fix."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [
        _sample_post(0, text="check out abcdcx nothing to see here, just a random word")
    ]

    body = await _preview_ok(
        preview_client, organization_id, name="DC", hashtags=["#DC"], directors=["Zack Snyder"]
    )

    assert body["posts"][0]["matched_terms"] == []


async def test_bare_term_still_matches_its_hashtag_form_across_the_hash_boundary(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """`96movie` must still be found inside `#96movie` — the hash is not a word
    character, so this cross-boundary match is unrelated to joiner folding and must
    keep working."""
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text="loving the vibe #96movie fdfs")]

    body = await _preview_ok(preview_client, organization_id, aliases=["96movie"])

    assert "96movie" in body["posts"][0]["matched_terms"]


async def test_emoji_zwj_sequence_does_not_become_a_hashtag_or_a_false_match(
    preview_client: AsyncClient, fake_search: FakeSearch
) -> None:
    """A ZWJ-joined family emoji immediately after a `#` must not be extracted as a
    hashtag at all — emoji are not word characters, joiner or not — and must not
    disturb the genuine match on the declared hashtag sitting right next to it."""
    family_emoji = "\U0001f468‍\U0001f469‍\U0001f467"
    organization_id = await _create_organization(preview_client)
    fake_search.posts = [_sample_post(0, text=f"#{family_emoji} #Vaaranam so proud")]

    body = await _preview_ok(preview_client, organization_id)

    post = body["posts"][0]
    assert post["candidate_exclusion_terms"] == []
    assert "Vaaranam" in post["matched_terms"]

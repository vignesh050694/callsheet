"""Tests for E02-S01 — Describe a title richly at setup so collection finds the film
and not its namesakes.

Story: stories/E02-title-setup-identity-discovery/E02-S01-create-title-with-rich-identity.md

The story has one Gherkin scenario ("Owner sets up a two-letter title that collides
with a global franchise"). Its Given/When/Then clauses map to test sections below:

  - "Given: I am an owner in a production house organization" -> baseline precondition,
    exercised by every test that creates a title as `api_client` (the owner of the org
    it creates).
  - "and Given: the setup form has fields for title name, alternate names, official
    hashtags, lead cast, director, and music director" -> the form is frontend (out of
    scope per the task brief); its backend contract is that `TitleCreate` accepts and
    stores all six kinds. Section 1.
  - "and Given: the form explains that a short or generic name needs at least one
    anchor term (a cast or crew name) to be collectable" -> the explanation is UI copy,
    untestable here; its backend-observable half is that the rejection message actually
    names the anchor requirement. Section 2.
  - "and Given: the form blocks submission of a name under four characters with no
    anchor term" -> the blocking rule itself, enforced server-side regardless of what
    the form does. Section 2.
  - "When: I enter the title name, its official hashtags, and the director and lead
    cast, and save" / "Then: the title is created with a stored identity set combining
    name, aliases, hashtags, and people, and that combined set — not the bare name — is
    what collection queries against" -> the central claim. Section 3, tested both as the
    exact scenario (two-letter title, hashtags + director + cast) and generalised
    (aliases and every people field contribute; the set is never just the name).

Additional sections cover behaviour the story's Notes and the task brief call out
explicitly as worth pinning down: normalisation/dedupe (Section 4), term-type storage
and `has_anchor_term` (Section 5), authorization (Section 6), organization scoping
(Section 7), and input hygiene — empty name, blank list entries (Section 8).

Section 9 covers two bugs a reviewer found after the first pass of this suite, now
fixed in the implementation:

  - BUG 1: the anchor rule could be satisfied by an invisible character. `str.strip()`
    does not remove the zero-width family (ZWSP, ZWNJ, ZWJ, BOM — Unicode category Cf),
    so a lone zero-width space in `lead_cast` read as a real cast member and satisfied
    `_ensure_name_is_collectable` for "DC" — the story's own franchise-collision
    example. Fixed via `has_meaningful_content`, which is true only when at least one
    character is outside categories Cc/Cf/Zl/Zp/Zs, used to filter terms, the name
    check, and `collection_terms_for`.
  - BUG 2: `normalize_term` used `removeprefix("#")`, stripping only one leading hash,
    so "##DC" normalised to "#dc" and did not dedupe against "#DC"/"DC". Fixed via
    `lstrip("#")`.

Section 11 covers a second review round, which found the Bug 1/2 fix itself was
incomplete:

  - BUG 3: Unicode category membership was the wrong proxy for "renders blank".
    `has_meaningful_content` only treated Cc/Cf/Zl/Zp/Zs as invisible, but several
    filler/blank code points are classified as letters (Lo) or symbols (So) — HANGUL
    FILLER and friends, BRAILLE PATTERN BLANK — and sailed through, satisfying the
    anchor rule exactly like a ZWSP did. Fixed via an explicit
    `_BLANK_RENDERING_CHARACTERS` set, checked in addition to the category test.
  - BUG 4: the anchor rule measured `len(name)`, i.e. code points, so one visible
    glyph padded with combining marks, or an emoji ZWJ sequence, could cross the
    4-character threshold without being four characters of anything. Fixed via
    `visible_length`, which counts only base characters — skipping invisible code
    points and combining marks (categories Mn/Mc/Me at the time) — and is now what
    `_ensure_name_is_collectable` measures instead of `len()`.

Section 12 covers a third review round:

  - FIX A: `Field(max_length=...)` on a bare `list[str]` bounds the LIST, not the
    strings inside it — an over-long term reached the `String(300)` column and would
    have produced a 500 on Postgres (SQLite, which this suite runs on, does not
    enforce VARCHAR limits, so nothing here caught it). Fixed via
    `TermList = list[Annotated[str, Field(max_length=TITLE_TERM_MAX_LENGTH)]]`.
  - FIX B: `visible_length` excluded category Mc along with Mn/Me, but Mc ("spacing
    combining mark") is exactly the category of the vowel signs in Devanagari, Telugu,
    Tamil and their neighbours — they occupy real rendered width and are part of the
    word, not decoration on it. Excluding them undercounted ordinary regional titles.
    Fixed by narrowing `_COMBINING_MARK_CATEGORIES` to `{Mn, Me}` only, so Mc now
    counts. This changes the numbers Section 11 pinned for "தமி" (2 -> 3) and
    "வாரணம்" (4 -> 5); both are corrected below along with the tests that depended
    on them. The outcome for "வாரணம்" is unchanged (still accepted bare, since 5 >= 4
    either way) — only the measured count moved.

Every assertion below that could be satisfied by two different rejection paths (e.g.
"empty name" vs. "unanchored name", both 422/ValidationFailedError) asserts on the
exact message, not just the status code — a test that only checks the status code
would still pass even if the anchor check were deleted entirely, since the *other*
validation path produces the identical status code.
"""

import unicodedata
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity_terms import has_meaningful_content, visible_length
from app.models import Title, TitleTerm, User
from app.models.title import TITLE_TERM_MAX_LENGTH
from app.schemas.title import MAX_TERMS_PER_FIELD

ORGANIZATIONS_URL = "/api/v1/organizations"
INVITATIONS_URL = "/api/v1/invitations"
ACCEPT_URL = f"{INVITATIONS_URL}/accept"

SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}

# Mirrors app/services/title_service.py's exact wording, so tests can distinguish the
# two 422 paths ("no name at all" vs. "short name, no anchor") by message rather than
# by status code alone — the two paths share a status code but must never share a cause.
UNANCHORED_NAME_MESSAGE = (
    "A title name shorter than 4 characters needs at least one cast or crew name "
    "to anchor it, otherwise collection cannot tell it apart from anything else with that name"
)
EMPTY_NAME_MESSAGE = "A title needs a name"


def _titles_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/titles"


def _title_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}"


def _invite_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/invitations"


async def _create_organization(client: AsyncClient, payload: dict = SUN_PICTURES_PAYLOAD) -> str:
    response = await client.post(ORGANIZATIONS_URL, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _invite(
    client: AsyncClient, organization_id: str, email: str, role: str = "viewer"
) -> dict:
    response = await client.post(_invite_url(organization_id), json={"email": email, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


async def _accept(client: AsyncClient, token: str) -> None:
    response = await client.post(ACCEPT_URL, json={"token": token})
    assert response.status_code == 204, response.text


async def _make_viewer(
    owner_client: AsyncClient, viewer_client: AsyncClient, organization_id: str, email: str
) -> None:
    """Invites `email` into `organization_id` as a viewer and accepts on `viewer_client`.

    Follows the pattern established in test_invite_teammate_with_role.py.
    """
    invitation = await _invite(owner_client, organization_id, email, "viewer")
    await _accept(viewer_client, invitation["token"])


def _create_payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "Vaaranam",
        # Required since E02-S02. These tests are about the identity set, so the date is
        # just a value that has to be present — E02-S02's own tests exercise the boundary.
        "release_date": "2026-09-11",
        "aliases": [],
        "hashtags": [],
        "lead_cast": [],
        "directors": [],
        "music_directors": [],
    }
    payload.update(overrides)
    return payload


async def _create_title(client: AsyncClient, organization_id: str, **overrides: object) -> dict:
    response = await client.post(_titles_url(organization_id), json=_create_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Section 1 — Given: the form has fields for name, aliases, hashtags, lead cast,
# director, and music director, and the backend stores all six kinds.
# ---------------------------------------------------------------------------


async def test_create_title_accepts_all_six_identity_fields(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Vaaranam Aayiram",
        aliases=["VA"],
        hashtags=["#VaaranamAayiram"],
        lead_cast=["Suriya"],
        directors=["Gautham Menon"],
        music_directors=["Harris Jayaraj"],
    )

    term_types_by_value = {term["value"]: term["term_type"] for term in body["terms"]}
    assert term_types_by_value["VA"] == "alias"
    assert term_types_by_value["#VaaranamAayiram"] == "hashtag"
    assert term_types_by_value["Suriya"] == "cast"
    assert term_types_by_value["Gautham Menon"] == "director"
    assert term_types_by_value["Harris Jayaraj"] == "music_director"


# ---------------------------------------------------------------------------
# Section 2 — Given: the form explains a short/generic name needs an anchor term, and
# blocks submission of a name under four characters with no anchor term.
# ---------------------------------------------------------------------------


async def test_short_name_with_no_terms_at_all_is_blocked(api_client: AsyncClient) -> None:
    """A name under four characters with nothing else attached is refused."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(_titles_url(organization_id), json=_create_payload(name="96"))

    assert response.status_code == 422
    assert response.json()["code"] == "ValidationFailedError"


async def test_short_name_with_only_a_hashtag_is_still_blocked(api_client: AsyncClient) -> None:
    """A hashtag is not an anchor term — only cast/crew names are. A short name backed
    only by a hashtag must be refused exactly like one backed by nothing."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="96", hashtags=["#96Movie"]),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ValidationFailedError"


async def test_short_name_with_only_an_alias_is_still_blocked(api_client: AsyncClient) -> None:
    """An alias is a name, not a person — it is not an anchor term either."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="96", aliases=["Ninety Six"]),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "ValidationFailedError"


async def test_short_name_rejection_message_explains_the_anchor_requirement(
    api_client: AsyncClient,
) -> None:
    """The form's job (per the story) is to make the anchor requirement unavoidable;
    the backend's part of that is a rejection message that actually names it."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(_titles_url(organization_id), json=_create_payload(name="96"))

    message = response.json()["message"].lower()
    assert "cast" in message or "crew" in message
    assert "4" in message or "four" in message


async def test_short_name_with_lead_cast_term_succeeds(api_client: AsyncClient) -> None:
    """A cast name is an anchor term: the same short name that was refused above must
    now be accepted."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="96", lead_cast=["Vijay Sethupathi"]),
    )

    assert response.status_code == 201, response.text


async def test_short_name_with_director_term_succeeds(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="96", directors=["Prem Kumar"]),
    )

    assert response.status_code == 201, response.text


async def test_short_name_with_music_director_term_succeeds(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="96", music_directors=["Govind Vasantha"]),
    )

    assert response.status_code == 201, response.text


async def test_four_character_name_with_no_terms_succeeds(api_client: AsyncClient) -> None:
    """The block is specifically "under four characters" — four characters is enough
    on its own."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name="Aaru")
    )

    assert response.status_code == 201, response.text


# ---------------------------------------------------------------------------
# Section 3 — When/Then: the central claim. The title is created with a stored
# identity set combining name, aliases, hashtags, and people — and that combined set,
# not the bare name, is what collection queries against.
# ---------------------------------------------------------------------------


async def test_two_letter_title_scenario_produces_a_collection_set_beyond_the_bare_name(
    api_client: AsyncClient,
) -> None:
    """The story's own example: a two-letter title colliding with a global franchise.
    Name, hashtags, director, and lead cast are entered together; the resulting
    collection set must contain all of it, not just the two-letter name."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="96",
        hashtags=["#96Movie"],
        directors=["Prem Kumar"],
        lead_cast=["Vijay Sethupathi", "Trisha"],
    )

    collection_terms = set(body["collection_terms"])
    assert "96" in collection_terms
    assert "96movie" in collection_terms
    assert "prem kumar" in collection_terms
    assert "vijay sethupathi" in collection_terms
    assert "trisha" in collection_terms
    # The bare name alone is explicitly not what collection queries against.
    assert collection_terms != {"96"}
    assert len(collection_terms) == 5


async def test_collection_terms_combine_name_aliases_hashtags_and_every_people_field(
    api_client: AsyncClient,
) -> None:
    """Generalised claim: every field the form offers contributes to the one combined
    set — not just the fields the story's example happens to use."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Vaaranam Aayiram",
        aliases=["VA"],
        hashtags=["#VaaranamAayiram"],
        lead_cast=["Suriya"],
        directors=["Gautham Menon"],
        music_directors=["Harris Jayaraj"],
    )

    collection_terms = set(body["collection_terms"])
    assert collection_terms == {
        "vaaranam aayiram",
        "va",
        "vaaranamaayiram",
        "suriya",
        "gautham menon",
        "harris jayaraj",
    }


async def test_collection_terms_for_a_name_only_title_is_only_the_name(
    api_client: AsyncClient,
) -> None:
    """Sanity check on the other end: with no additional terms, the set correctly
    degrades to just the name — proving the combination logic adds terms rather than
    always returning some fixed larger set."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(api_client, organization_id, name="Aaru")

    assert body["collection_terms"] == ["aaru"]


async def test_stored_title_row_has_the_bare_name_and_terms_are_a_separate_table(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The identity set is stored as rows in `title_terms`, separate from `titles.name`
    — proving the "stored identity set" claim is backed by real persisted state, not
    just an API-response computation."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="96",
        hashtags=["#96Movie"],
        directors=["Prem Kumar"],
    )

    title_row = await db_session.get(Title, uuid.UUID(body["id"]))
    assert title_row.name == "96"

    term_rows = (
        (await db_session.execute(select(TitleTerm).where(TitleTerm.title_id == title_row.id)))
        .scalars()
        .all()
    )
    assert len(term_rows) == 2
    normalized_values = {term.normalized_value for term in term_rows}
    assert normalized_values == {"96movie", "prem kumar"}


# ---------------------------------------------------------------------------
# Section 4 — Normalisation and dedupe: variant spellings of the same term collapse to
# one stored term and one collection entry; `value` preserves what was typed while
# `normalized_value` is the comparable form.
# ---------------------------------------------------------------------------


async def test_hashtag_variants_collapse_to_a_single_stored_term(api_client: AsyncClient) -> None:
    """ "#96Movie", "96movie", and "  #96MOVIE  " are the same hashtag under
    normalisation (NFKC, strip, drop leading '#', collapse whitespace, casefold) and
    must dedupe to exactly one stored term."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Ninety Six",
        hashtags=["#96Movie", "96movie", "  #96MOVIE  "],
    )

    hashtag_terms = [term for term in body["terms"] if term["term_type"] == "hashtag"]
    assert len(hashtag_terms) == 1


async def test_hashtag_variants_collapse_to_a_single_collection_term(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Ninety Six",
        hashtags=["#96Movie", "96movie", "  #96MOVIE  "],
    )

    hashtag_collection_entries = [term for term in body["collection_terms"] if "96" in term]
    assert hashtag_collection_entries == ["96movie"]


async def test_stored_value_preserves_typed_form_while_normalized_value_is_comparable(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """The first-typed variant is what is shown back (`value`), tidied but not
    case-folded or stripped of its hash; `normalized_value` is the folded, hash-free,
    whitespace-collapsed comparable form used for dedupe and matching."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Ninety Six",
        hashtags=["#96Movie", "96movie", "  #96MOVIE  "],
    )

    hashtag_term = next(term for term in body["terms"] if term["term_type"] == "hashtag")
    assert hashtag_term["value"] == "#96Movie"

    title_row = await db_session.get(Title, uuid.UUID(body["id"]))
    term_rows = (
        (await db_session.execute(select(TitleTerm).where(TitleTerm.title_id == title_row.id)))
        .scalars()
        .all()
    )
    assert len(term_rows) == 1
    assert term_rows[0].value == "#96Movie"
    assert term_rows[0].normalized_value == "96movie"


async def test_same_display_text_in_different_term_types_is_not_deduped_across_types(
    api_client: AsyncClient,
) -> None:
    """Dedupe is scoped to (term_type, normalized_value) at the storage layer — the
    same text as both an alias and a hashtag is two different kinds of term and both
    are kept, though the collection set (which is just normalised strings) folds them
    to one entry."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Ninety Six",
        aliases=["96"],
        hashtags=["96"],
    )

    assert len(body["terms"]) == 2
    term_types = {term["term_type"] for term in body["terms"]}
    assert term_types == {"alias", "hashtag"}
    # But the collection set, being just normalised text, only needs one "96" entry.
    assert body["collection_terms"].count("96") == 1


# ---------------------------------------------------------------------------
# Section 5 — Terms are stored under the right term_type, and has_anchor_term reflects
# whether any people terms exist.
# ---------------------------------------------------------------------------


async def test_has_anchor_term_is_true_when_lead_cast_present(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client, organization_id, name="Ninety Six", lead_cast=["Vijay Sethupathi"]
    )

    assert body["has_anchor_term"] is True


async def test_has_anchor_term_is_true_when_director_present(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client, organization_id, name="Ninety Six", directors=["Prem Kumar"]
    )

    assert body["has_anchor_term"] is True


async def test_has_anchor_term_is_true_when_music_director_present(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client, organization_id, name="Ninety Six", music_directors=["Govind Vasantha"]
    )

    assert body["has_anchor_term"] is True


async def test_has_anchor_term_is_false_when_only_alias_and_hashtag_present(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Ninety Six",
        aliases=["96"],
        hashtags=["#96Movie"],
    )

    assert body["has_anchor_term"] is False


async def test_has_anchor_term_is_false_when_no_terms_at_all(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(api_client, organization_id, name="Ninety Six")

    assert body["has_anchor_term"] is False


# ---------------------------------------------------------------------------
# Section 6 — Authorization: viewer forbidden (403), non-member not-found (404),
# unauthenticated unauthorized (401), and GET on an unannounced title is a 404
# indistinguishable from a missing one.
# ---------------------------------------------------------------------------


async def test_viewer_cannot_create_a_title(
    api_client: AsyncClient, other_api_client: AsyncClient, other_pilot_user: User
) -> None:
    """A viewer can see the organization (they are a member), so a refusal here is an
    honest 403, not a 404."""
    organization_id = await _create_organization(api_client)
    await _make_viewer(api_client, other_api_client, organization_id, other_pilot_user.email)

    response = await other_api_client.post(_titles_url(organization_id), json=_create_payload())

    assert response.status_code == 403
    assert response.json()["code"] == "PermissionDeniedError"


async def test_non_member_cannot_create_a_title(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    """A caller who is not a member at all gets the same 404 a missing organization id
    would get — a 403 here would confirm the organization exists."""
    organization_id = await _create_organization(api_client)

    response = await other_api_client.post(_titles_url(organization_id), json=_create_payload())

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_non_member_cannot_list_titles(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)

    response = await other_api_client.get(_titles_url(organization_id))

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_unauthenticated_cannot_create_a_title(
    api_client: AsyncClient, unauthenticated_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)

    response = await unauthenticated_client.post(
        _titles_url(organization_id), json=_create_payload()
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_unauthenticated_cannot_list_titles(
    api_client: AsyncClient, unauthenticated_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)

    response = await unauthenticated_client.get(_titles_url(organization_id))

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_unauthenticated_cannot_get_a_title(
    api_client: AsyncClient, unauthenticated_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)
    title = await _create_title(api_client, organization_id, name="Ninety Six")

    response = await unauthenticated_client.get(_title_url(title["id"]))

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_member_can_get_a_title(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)
    title = await _create_title(api_client, organization_id, name="Ninety Six")

    response = await api_client.get(_title_url(title["id"]))

    assert response.status_code == 200
    assert response.json()["id"] == title["id"]


async def test_non_member_get_title_returns_not_found(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    """Deliberately identical to a missing title: a non-member must not be able to
    confirm that an unannounced title exists just by probing its id."""
    organization_id = await _create_organization(api_client)
    title = await _create_title(api_client, organization_id, name="Ninety Six")

    response = await other_api_client.get(_title_url(title["id"]))

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_non_member_get_title_response_matches_a_genuinely_missing_title(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    """Not just the same status code — the same code/message, so a non-member cannot
    use response contents to distinguish "not yours" from "does not exist"."""
    organization_id = await _create_organization(api_client)
    title = await _create_title(api_client, organization_id, name="Ninety Six")

    not_your_title_response = await other_api_client.get(_title_url(title["id"]))
    genuinely_missing_response = await other_api_client.get(
        _title_url("00000000-0000-0000-0000-000000000000")
    )

    assert not_your_title_response.status_code == genuinely_missing_response.status_code == 404
    assert not_your_title_response.json()["code"] == genuinely_missing_response.json()["code"]


async def test_viewer_can_read_a_title(
    api_client: AsyncClient, other_api_client: AsyncClient, other_pilot_user: User
) -> None:
    """A viewer is a member, so reading is allowed — only creation is owner-only."""
    organization_id = await _create_organization(api_client)
    title = await _create_title(api_client, organization_id, name="Ninety Six")
    await _make_viewer(api_client, other_api_client, organization_id, other_pilot_user.email)

    response = await other_api_client.get(_title_url(title["id"]))

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Section 7 — List is scoped to the organization.
# ---------------------------------------------------------------------------


async def test_list_titles_is_scoped_to_the_organization(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    sun_pictures_id = await _create_organization(api_client)
    ravi_films_id = await _create_organization(
        other_api_client,
        {"name": "Ravi Films", "slug": "ravi-films", "organization_type": "production_house"},
    )
    await _create_title(api_client, sun_pictures_id, name="Vaaranam Aayiram")
    await _create_title(other_api_client, ravi_films_id, name="Some Other Film")

    response = await api_client.get(_titles_url(sun_pictures_id))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["name"] for item in body["items"]] == ["Vaaranam Aayiram"]


# ---------------------------------------------------------------------------
# Section 8 — Input hygiene: empty/whitespace-only name refused; blank entries inside
# a term list are dropped rather than stored.
# ---------------------------------------------------------------------------


async def test_empty_name_is_refused(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    response = await api_client.post(_titles_url(organization_id), json=_create_payload(name=""))

    assert response.status_code == 422


async def test_whitespace_only_name_is_refused(api_client: AsyncClient) -> None:
    """Passes pydantic's `min_length=1` (whitespace is a character) but must still be
    refused once the service cleans it down to nothing."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(_titles_url(organization_id), json=_create_payload(name="   "))

    assert response.status_code == 422
    assert response.json()["code"] == "ValidationFailedError"


async def test_blank_entries_inside_a_term_list_are_dropped_not_stored(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Ninety Six",
        lead_cast=["", "  ", "Trisha"],
    )

    cast_terms = [term for term in body["terms"] if term["term_type"] == "cast"]
    assert len(cast_terms) == 1
    assert cast_terms[0]["value"] == "Trisha"


async def test_blank_entries_do_not_appear_in_collection_terms(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Ninety Six",
        lead_cast=["", "  ", "Trisha"],
    )

    assert "" not in body["collection_terms"]
    assert set(body["collection_terms"]) == {"ninety six", "trisha"}


# ---------------------------------------------------------------------------
# Section 9 — Bug fixes: invisible characters cannot forge an anchor term (Bug 1),
# and every leading hash is stripped for dedupe purposes, not just one (Bug 2).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "invisible_term",
    ["​", "‌", "‍", "﻿", "   "],
    ids=["zwsp", "zwnj", "zwj", "bom", "whitespace_only"],
)
async def test_invisible_only_cast_term_does_not_satisfy_the_anchor_rule(
    api_client: AsyncClient, invisible_term: str
) -> None:
    """The reviewer's exact attack, generalised across the whole invisible family: a
    lone zero-width space, ZWNJ, ZWJ, BOM, or a whitespace-only string in `lead_cast`
    is not a real cast member. "DC" is the story's own franchise-collision example —
    if this were accepted, the acceptance criterion would not actually be enforced.

    Asserted on the exact message, not just the 422/ValidationFailedError status: the
    empty-name path produces the identical status and code, so only the anchor-specific
    message proves the anchor check itself — not some other check — is what caught
    this. This is deliberately the same shape of assertion the previous suite was
    missing: a status-code-only check here would still have passed with Bug 1 present,
    because the request without the fix returns 201, not a different flavour of 422 —
    but that gap matters generally, so the message is pinned everywhere in this section.
    """
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="DC", lead_cast=[invisible_term]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == UNANCHORED_NAME_MESSAGE

    # Nothing was created: the org's title list must still be empty.
    list_response = await api_client.get(_titles_url(organization_id))
    assert list_response.json()["total"] == 0


@pytest.mark.parametrize(
    "invisible_name",
    ["​​​", "﻿", "   ", "‌‍"],
    ids=["zwsp_run", "bom", "whitespace_only", "zwnj_zwj"],
)
async def test_name_of_only_invisible_characters_is_refused_even_with_a_real_anchor_term(
    api_client: AsyncClient, invisible_name: str
) -> None:
    """A name that is nothing but invisible characters must be refused as an empty
    name — even when a real cast member is supplied, because a real anchor term
    cannot rescue a name that, once cleaned, isn't there at all.

    Asserted on the exact message specifically so this cannot be conflated with the
    anchor-rule rejection above: this must be `EMPTY_NAME_MESSAGE`, not
    `UNANCHORED_NAME_MESSAGE` — two different rules, two different messages, and a
    real anchor term present proves it was the *name* check that fired, not the
    anchor check (which would have passed)."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name=invisible_name, lead_cast=["Vijay Sethupathi"]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == EMPTY_NAME_MESSAGE
    assert body["message"] != UNANCHORED_NAME_MESSAGE


async def test_cast_term_with_invisible_edge_characters_is_cleaned_and_counts_as_anchor(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A term with invisible characters only at its edges is not garbage — it is a
    real term that needs cleaning. "​Trisha​" must store and normalise as
    plain "Trisha"/"trisha", exactly as if the invisible characters had never been
    there, and it must count as a genuine anchor term (rescuing the short name "DC")."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="DC",
        lead_cast=["​Trisha​"],
    )

    cast_term = next(term for term in body["terms"] if term["term_type"] == "cast")
    assert cast_term["value"] == "Trisha"
    assert body["has_anchor_term"] is True
    assert "trisha" in body["collection_terms"]

    title_row = await db_session.get(Title, uuid.UUID(body["id"]))
    term_rows = (
        (await db_session.execute(select(TitleTerm).where(TitleTerm.title_id == title_row.id)))
        .scalars()
        .all()
    )
    assert len(term_rows) == 1
    assert term_rows[0].value == "Trisha"
    assert term_rows[0].normalized_value == "trisha"


async def test_inner_zero_width_non_joiner_is_preserved_not_stripped(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """CRITICAL regression guard against the fix over-reaching into a strip-all: ZWNJ
    and ZWJ carry real meaning inside Indic scripts and emoji sequences, so cleaning
    may only ever touch a term's EDGES. A Tamil term with an inner ZWNJ must round-trip
    with that character still present — in both the displayed `value` and the
    `normalized_value` collection matches on. If someone "simplified" the fix by
    stripping every invisible character everywhere instead of only at the edges, this
    is the test that would catch it: the inner ZWNJ would silently vanish and this
    assertion would fail."""
    organization_id = await _create_organization(api_client)
    tamil_term_with_inner_zwnj = "தமிழ்‌சினிமா"
    assert "‌" in tamil_term_with_inner_zwnj  # sanity: the fixture itself has one

    body = await _create_title(
        api_client,
        organization_id,
        name="Vaaranam Aayiram",
        aliases=[tamil_term_with_inner_zwnj],
    )

    alias_term = next(term for term in body["terms"] if term["term_type"] == "alias")
    assert alias_term["value"] == tamil_term_with_inner_zwnj
    assert "‌" in alias_term["value"]

    title_row = await db_session.get(Title, uuid.UUID(body["id"]))
    term_rows = (
        (await db_session.execute(select(TitleTerm).where(TitleTerm.title_id == title_row.id)))
        .scalars()
        .all()
    )
    assert len(term_rows) == 1
    assert term_rows[0].normalized_value == tamil_term_with_inner_zwnj
    assert "‌" in term_rows[0].normalized_value
    assert term_rows[0].normalized_value in body["collection_terms"]


async def test_hash_variants_of_varying_length_all_dedupe_to_one_stored_hashtag_term(
    api_client: AsyncClient,
) -> None:
    """ "#DC", "##DC", "###dc", and "DC" must all collapse into a single stored
    hashtag term. Before the fix, `normalize_term` used `removeprefix("#")`, which
    strips only one leading hash, so "##DC" normalised to "#dc" — a value that still
    carries a hash and does not match "dc" from "DC" or "#DC". `lstrip("#")` strips
    every leading hash, so all four variants land on the identical normalised form."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Ninety Six",
        hashtags=["#DC", "##DC", "###dc", "DC"],
    )

    hashtag_terms = [term for term in body["terms"] if term["term_type"] == "hashtag"]
    assert len(hashtag_terms) == 1
    assert hashtag_terms[0]["value"] == "#DC"  # the first-typed variant is kept
    assert body["collection_terms"].count("dc") == 1


async def test_hashtag_that_is_only_hash_characters_is_dropped(api_client: AsyncClient) -> None:
    """ "#", "##", and "###" all normalise (via `lstrip("#")` reducing them to the
    empty string) to nothing with meaningful content — none of them may be stored as a
    term, and none may appear in the collection set."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Ninety Six",
        hashtags=["#", "##", "###"],
    )

    hashtag_terms = [term for term in body["terms"] if term["term_type"] == "hashtag"]
    assert hashtag_terms == []
    assert "" not in body["collection_terms"]
    assert body["collection_terms"] == ["ninety six"]


# ---------------------------------------------------------------------------
# Section 10 — Unit coverage for `has_meaningful_content` itself: the whole
# invisible-character fix depends on it drawing the "is this actually a term" line in
# the right place, so it is worth pinning down directly rather than only through the
# API-level behaviour above.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", False),
        ("   ", False),
        ("​", False),  # ZWSP
        ("‌", False),  # ZWNJ
        ("‍", False),  # ZWJ
        ("﻿", False),  # BOM
        ("​‌‍﻿   ", False),  # every invisible kind, combined
        ("a", True),
        ("DC", True),
        # Visible punctuation, not invisible: `has_meaningful_content("#")` is True.
        # The end-to-end drop-on-"#" behaviour (tested above) comes from
        # `normalize_term`'s `lstrip("#")` reducing it to "" first, not from this
        # function treating "#" itself as meaningless.
        ("#", True),
        ("​Trisha​", True),  # invisible edges around real content
        ("தமிழ்‌சினிமா", True),  # inner ZWNJ around real content
    ],
    ids=[
        "empty_string",
        "whitespace_only",
        "zwsp",
        "zwnj",
        "zwj",
        "bom",
        "all_invisible_kinds_combined",
        "single_letter",
        "plain_word",
        "bare_hash_is_visible_punctuation_not_invisible",
        "invisible_edges_around_real_content",
        "inner_zwnj_around_real_content",
    ],
)
def test_has_meaningful_content_unit(value: str, expected: bool) -> None:
    assert has_meaningful_content(value) is expected


# ---------------------------------------------------------------------------
# Section 11 — Bug fixes, second review round: category membership was the wrong
# proxy for "renders blank" (Bug 3), and the anchor rule's length check counted code
# points instead of visible glyphs (Bug 4).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "blank_rendering_character",
    ["ᅟ", "ᅠ", "ㅤ", "ﾠ", "⠀"],
    ids=[
        "hangul_choseong_filler_u115f",
        "hangul_jungseong_filler_u1160",
        "hangul_filler_u3164",
        "halfwidth_hangul_filler_uffa0",
        "braille_pattern_blank_u2800",
    ],
)
async def test_blank_rendering_letter_or_symbol_cast_term_does_not_satisfy_the_anchor_rule(
    api_client: AsyncClient, blank_rendering_character: str
) -> None:
    """These five code points paint nothing on screen but are classified as LETTERS
    (Lo) or SYMBOLS (So), not as any of the Cc/Cf/Zl/Zp/Zs categories the first fix
    checked — so a Unicode-category-only test let every one of them through as a real
    cast member, exactly as the ZWSP from Bug 1 did. Each, alone in `lead_cast` against
    the story's own franchise-collision name "DC", must now be refused.

    Asserted on the exact message, not just 422/ValidationFailedError: the empty-name
    path returns the identical status and code, so only `UNANCHORED_NAME_MESSAGE`
    proves the anchor check — not some unrelated check — is what caught this."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="DC", lead_cast=[blank_rendering_character]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == UNANCHORED_NAME_MESSAGE

    list_response = await api_client.get(_titles_url(organization_id))
    assert list_response.json()["total"] == 0


async def test_name_of_only_blank_rendering_characters_is_refused_as_empty(
    api_client: AsyncClient,
) -> None:
    """A name built entirely out of blank-rendering filler characters is not a name,
    even with a real cast member supplied — same shape as the Bug 1 empty-name test,
    now for the letter/symbol-classified blanks instead of the Cf-classified ones.
    Asserted on `EMPTY_NAME_MESSAGE` specifically, distinguishing it from the
    anchor-rule rejection above."""
    organization_id = await _create_organization(api_client)
    blank_name = "ᅟᅠㅤﾠ⠀"

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name=blank_name, lead_cast=["Vijay Sethupathi"]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == EMPTY_NAME_MESSAGE
    assert body["message"] != UNANCHORED_NAME_MESSAGE


async def test_ideographic_space_only_name_is_refused_via_the_existing_category_test(
    api_client: AsyncClient,
) -> None:
    """U+3000 IDEOGRAPHIC SPACE is category Zs — it was already covered by the
    original `_INVISIBLE_CATEGORIES` test, not by the new explicit blank-rendering
    set. Included here as a boundary check that the category test and the explicit
    set compose correctly, not as a claim that U+3000 is in the explicit set."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="　　　　", lead_cast=["Vijay Sethupathi"]),
    )

    assert response.status_code == 422, response.text
    assert response.json()["message"] == EMPTY_NAME_MESSAGE


@pytest.mark.parametrize(
    "value,expected",
    [
        ("DC", 2),
        ("D́̂̃", 1),  # one letter + 3 combining accents, one grapheme cluster
        # Family emoji, ZWJ-joined: three emoji fused by ZWJ into one cluster (E02-S07).
        # Superseded Fix B's number of 3 — Mc/Mn no longer matters here at all, since
        # what collapses this to one is the ZWJ binding, not mark-category membership.
        ("\U0001f468‍\U0001f469‍\U0001f467", 1),
        ("Aaru", 4),
        # Grapheme clustering (E02-S07): every mark, spacing (Mc) or not (Mn/Me), folds
        # into the base character before it, because it is visible *as part of that
        # character's cluster*, not as a glyph of its own. "தமி" is த (Lo) + ம+ி
        # (Lo base with its Mc vowel sign folded in) = 2 clusters, not 3 — Fix B's count
        # before this story counted the vowel sign separately and got 3.
        ("தமி", 2),
        # "வாரணம்" is 6 code points: வ ா ர ண ம ். Grapheme clustering folds ா (Mc) into
        # வ, and ் (Mn, virama) into ம், giving 4 clusters: வா, ர, ண, ம். Fix B's
        # spacing-marks-count-separately rule had this at 5.
        ("வாரணம்", 4),
        # Hindi "Radhe" is र ा ध े: र+ा (RA + its Mc vowel sign) is one cluster/syllable,
        # and ध+े (DHA + its Mn vowel sign) is another — 2 clusters, not the 4 code
        # points. Fix B's count (spacing marks count separately) was 3.
        ("राधे", 2),
        ("మజిలీ", 3),  # Telugu "Majili": Mn-only vowel signs, unaffected by this story
    ],
    ids=[
        "dc_two_plain_letters",
        "one_letter_three_combining_accents",
        "family_emoji_zwj_sequence_one_cluster",
        "aaru_four_letters",
        "tamil_two_grapheme_clusters",
        "tamil_six_code_points_four_grapheme_clusters",
        "hindi_radhe_two_grapheme_clusters",
        "telugu_majili_three_visible_mn_only",
    ],
)
def test_visible_length_unit(value: str, expected: int) -> None:
    assert visible_length(value) == expected


def test_telugu_majili_contains_no_mc_characters() -> None:
    """Guards the reasoning behind the Mc fix, not just its numeric outcome: "మజిలీ"
    ends up with the same `visible_length` (3) both before and after Fix B, because
    both of its vowel signs (ి and ీ) are Mn, not Mc. Anyone re-reading Fix B later
    must not assume the Mc change is what altered this particular title's count —
    it didn't, and this test would fail if a future change made it start containing
    an Mc character while this assertion still claimed otherwise."""
    telugu_majili = "మజిలీ"

    categories = {unicodedata.category(character) for character in telugu_majili}

    assert "Mc" not in categories
    assert categories == {"Lo", "Mn"}


async def test_name_padded_with_combining_marks_to_four_code_points_is_still_blocked(
    api_client: AsyncClient,
) -> None:
    """ "D" plus three combining accents is 4 code points (`len() == 4`) but exactly one
    visible glyph (`visible_length() == 1`) — the old `len()`-based check would have
    let this through unanchored; `visible_length()` must not."""
    organization_id = await _create_organization(api_client)
    padded_name = "D́̂̃"
    assert len(padded_name) == 4
    assert visible_length(padded_name) == 1

    response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=padded_name)
    )

    assert response.status_code == 422, response.text
    assert response.json()["message"] == UNANCHORED_NAME_MESSAGE


async def test_family_emoji_name_with_five_code_points_one_glyph_is_still_blocked(
    api_client: AsyncClient,
) -> None:
    """The family emoji is 5 code points (`len() == 5`, past the old threshold) but one
    glyph and, under grapheme clustering (E02-S07), one visible character — the ZWJs
    fuse all three emoji into a single cluster. Still well under the anchor threshold,
    and still must be blocked without an anchor term."""
    organization_id = await _create_organization(api_client)
    family_emoji_name = "\U0001f468‍\U0001f469‍\U0001f467"
    assert len(family_emoji_name) == 5
    assert visible_length(family_emoji_name) == 1

    response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=family_emoji_name)
    )

    assert response.status_code == 422, response.text
    assert response.json()["message"] == UNANCHORED_NAME_MESSAGE


async def test_combining_mark_padded_name_succeeds_with_a_real_anchor_term(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    padded_name = "D́̂̃"

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name=padded_name, lead_cast=["Vijay Sethupathi"]),
    )

    assert response.status_code == 201, response.text
    assert response.json()["has_anchor_term"] is True


async def test_family_emoji_name_succeeds_with_a_real_anchor_term(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    family_emoji_name = "\U0001f468‍\U0001f469‍\U0001f467"

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name=family_emoji_name, lead_cast=["Vijay Sethupathi"]),
    )

    assert response.status_code == 201, response.text
    assert response.json()["has_anchor_term"] is True


# --- Regression guards: the Bug 3/4 fixes must not over-reach into terms or into
# legitimate short titles in scripts this product exists to serve. ---


async def test_emoji_zwj_sequence_alias_round_trips_with_joiners_intact(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A ZWJ-joined emoji sequence is a legitimate alias term, not a fake anchor —
    `visible_length` only applies to the *name* threshold, and `has_meaningful_content`
    must not strip the ZWJs out of a term that legitimately contains them (mirrors the
    inner-ZWNJ Tamil guard, for emoji instead of Indic script). Stored and returned
    value must be byte-for-byte the same sequence that was submitted."""
    organization_id = await _create_organization(api_client)
    family_emoji = "\U0001f468‍\U0001f469‍\U0001f467"

    body = await _create_title(
        api_client,
        organization_id,
        name="Vaaranam Aayiram",
        aliases=[family_emoji],
    )

    alias_term = next(term for term in body["terms"] if term["term_type"] == "alias")
    assert alias_term["value"] == family_emoji
    assert "‍" in alias_term["value"]

    title_row = await db_session.get(Title, uuid.UUID(body["id"]))
    term_rows = (
        (await db_session.execute(select(TitleTerm).where(TitleTerm.title_id == title_row.id)))
        .scalars()
        .all()
    )
    assert term_rows[0].normalized_value == family_emoji
    assert "‍" in term_rows[0].normalized_value


async def test_inner_zwnj_tamil_alias_guard_still_passes(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Re-asserts the Section 9 guard still holds after the Bug 3/4 fixes: an inner
    ZWNJ inside a Tamil alias must remain untouched — this is the test that would
    catch a future "simplify invisible-handling" change deleting the edges-only
    behaviour the earlier fix relied on."""
    organization_id = await _create_organization(api_client)
    tamil_term_with_inner_zwnj = "தமிழ்‌சினிமா"
    assert "‌" in tamil_term_with_inner_zwnj

    body = await _create_title(
        api_client,
        organization_id,
        name="Vaaranam Aayiram",
        aliases=[tamil_term_with_inner_zwnj],
    )

    alias_term = next(term for term in body["terms"] if term["term_type"] == "alias")
    assert alias_term["value"] == tamil_term_with_inner_zwnj
    assert "‌" in alias_term["value"]


async def test_real_short_tamil_title_is_accepted_with_no_anchor_term(
    api_client: AsyncClient,
) -> None:
    """CRITICAL: the visible-length fix must not make legitimate short Indic titles
    impossible to add without an anchor. "வாரணம்" is 6 code points and, under grapheme
    clustering (E02-S07: வா, ர, ண, ம் — one cluster per base with its marks folded in),
    4 visible characters — exactly at `MIN_UNANCHORED_NAME_LENGTH`, so it must still be
    accepted on the name alone. (Fix B, the review round before this story, had this
    title at 5 by counting the Mc vowel sign as its own character; E02-S07's grapheme
    counting moved it to 4. The outcome — accepted bare — is unchanged either way,
    since both 4 and 5 clear the threshold, but 4 is now exactly on the boundary rather
    than one past it — see test_measure_title_length_by_grapheme.py for a title that
    sits just under it.)"""
    organization_id = await _create_organization(api_client)
    tamil_title = "வாரணம்"
    assert len(tamil_title) == 6
    assert visible_length(tamil_title) == 4

    response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=tamil_title)
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["has_anchor_term"] is False
    assert body["collection_terms"] == [tamil_title]


# ---------------------------------------------------------------------------
# Section 12 — Bug fixes, third review round: an unbounded term string could reach the
# database column and fail as a 500 rather than a 422 (Fix A), and the visible-length
# rule undercounted Devanagari/Telugu/Tamil spacing vowel signs (Fix B).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    ["aliases", "hashtags", "lead_cast", "directors", "music_directors"],
)
async def test_5000_character_term_is_rejected_by_pydantic_in_every_term_field(
    api_client: AsyncClient, field_name: str
) -> None:
    """`Field(max_length=...)` on a bare `list[str]` only bounds the list length, not
    the strings inside it — before Fix A, a term this long would reach the
    `String(300)` column and fail downstream (a 500 on a database that enforces
    VARCHAR limits; SQLite, which this suite runs on, does not, which is why nothing
    here caught it before). Now each item is itself length-capped, so the request is
    rejected at the Pydantic layer, before it ever reaches the service. This is a
    genuine FastAPI/Pydantic validation failure, not one of the service's own domain
    errors — the body is FastAPI's `{"detail": [...]}` shape, not the app's
    `ErrorResponse` envelope (`code`/`message`/`request_id`), so assert accordingly."""
    organization_id = await _create_organization(api_client)
    overlong_term = "a" * 5000

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="Ninety Six", **{field_name: [overlong_term]}),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert "detail" in body
    assert "code" not in body  # confirms this is NOT our ErrorResponse envelope
    errors = body["detail"]
    assert any(
        error["type"] == "string_too_long" and error["loc"][:2] == ["body", field_name]
        for error in errors
    )


async def test_term_of_exactly_the_max_length_is_accepted(api_client: AsyncClient) -> None:
    """Pins the boundary from the accepted side: a term of exactly
    `TITLE_TERM_MAX_LENGTH` (300) characters must succeed."""
    organization_id = await _create_organization(api_client)
    boundary_term = "a" * TITLE_TERM_MAX_LENGTH
    assert len(boundary_term) == 300

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="Ninety Six", aliases=[boundary_term]),
    )

    assert response.status_code == 201, response.text
    alias_term = next(term for term in response.json()["terms"] if term["term_type"] == "alias")
    assert alias_term["value"] == boundary_term


async def test_term_one_over_the_max_length_is_refused(api_client: AsyncClient) -> None:
    """Pins the boundary from the refused side: one character past
    `TITLE_TERM_MAX_LENGTH` must fail — the fence is at exactly 300, not 301 or
    looser."""
    organization_id = await _create_organization(api_client)
    over_boundary_term = "a" * (TITLE_TERM_MAX_LENGTH + 1)
    assert len(over_boundary_term) == 301

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="Ninety Six", aliases=[over_boundary_term]),
    )

    assert response.status_code == 422, response.text
    assert "detail" in response.json()


async def test_more_than_max_terms_per_field_is_still_rejected(api_client: AsyncClient) -> None:
    """Fix A only added a per-item cap; the pre-existing per-list cap
    (`MAX_TERMS_PER_FIELD` = 50) must still work: 51 aliases must still be refused."""
    organization_id = await _create_organization(api_client)
    too_many_aliases = [f"alias{i}" for i in range(MAX_TERMS_PER_FIELD + 1)]
    assert len(too_many_aliases) == 51

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="Ninety Six", aliases=too_many_aliases),
    )

    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert any(
        error["type"] == "too_long" and error["loc"][:2] == ["body", "aliases"] for error in errors
    )


# --- Fix B: short regional titles by akshara are still short, and must still require
# an anchor — this is the intended reading of the rule, not an accident of which
# Unicode categories happen to be excluded. ---


async def test_hindi_radhe_still_requires_an_anchor_term_bare(api_client: AsyncClient) -> None:
    """ "राधे" (Radhe) has `visible_length` 2 under grapheme clustering (E02-S07) — by
    akshara, what a reader actually perceives, it is a genuinely short name, on the
    same footing as bare "DC". Refusing it without an anchor is the intended behaviour
    of the rule."""
    organization_id = await _create_organization(api_client)
    hindi_title = "राधे"
    assert visible_length(hindi_title) == 2

    response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=hindi_title)
    )

    assert response.status_code == 422, response.text
    assert response.json()["message"] == UNANCHORED_NAME_MESSAGE


async def test_hindi_radhe_succeeds_with_a_real_anchor_term(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)
    hindi_title = "राधे"

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name=hindi_title, lead_cast=["Prabhas"]),
    )

    assert response.status_code == 201, response.text
    assert response.json()["has_anchor_term"] is True


async def test_telugu_majili_still_requires_an_anchor_term_bare(api_client: AsyncClient) -> None:
    """ "మజిలీ" (Majili) has `visible_length` 3 — same reasoning as "राधे" above: a
    genuinely short regional title, correctly refused bare. Its count did not move
    between the pre- and post-Fix-B implementations (see
    `test_telugu_majili_contains_no_mc_characters`), so this specifically proves the
    rule's outcome for a real short title independent of which fix produced the
    number."""
    organization_id = await _create_organization(api_client)
    telugu_title = "మజిలీ"
    assert visible_length(telugu_title) == 3

    response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=telugu_title)
    )

    assert response.status_code == 422, response.text
    assert response.json()["message"] == UNANCHORED_NAME_MESSAGE


async def test_telugu_majili_succeeds_with_a_real_anchor_term(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)
    telugu_title = "మజిలీ"

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name=telugu_title, lead_cast=["Naga Chaitanya"]),
    )

    assert response.status_code == 201, response.text
    assert response.json()["has_anchor_term"] is True

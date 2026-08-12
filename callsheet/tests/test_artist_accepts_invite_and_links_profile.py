"""Tests for E01-S04 — Artist accepts a title invitation and links their profile.

Story: stories/E01-organizations-access-membership/
       E01-S04-artist-accepts-invite-and-links-profile.md

The story has exactly one Gherkin scenario ("Artist accepts a title invitation and confirms
their identity set"), covered end to end by the single test in Section 1. Its Given/When/Then
clauses map onto that one test as follows:

  - Given "a production house has tagged me on a title and sent me an invitation" -> the
    title is created with the actor on `lead_cast`, then tagged with a guessed identity set
    (a name variant and a handle) and a `contact_email` the acceptor's account will match.
  - Given "the acceptance flow pre-fills the name variants and handles the production house
    entered for me" -> the preview response's `name_variants`/`handles` are asserted against
    exactly what the tag call entered.
  - Given "I can add, correct, or remove any pre-filled variant before confirming" -> the
    accept payload removes the guessed short name, corrects the guessed handle's casing (same
    normalized identity, different display form), and adds a brand-new name variant and
    handle the production house never typed.
  - Given "the flow explains that the production house cannot see my personal dashboard" ->
    the preview's `privacy_notice` is asserted equal to the service's `PRIVACY_NOTICE`.
  - When "I accept the invitation and confirm my corrected identity set" -> the POST to
    `/titles/invitations/accept`.
  - Then "my artist entity is linked to my account" -> `Artist.linked_user_id` is read back
    via the DB session (not exposed on `ArtistRead`) and asserted to be the acceptor.
  - Then "the corrected variants are used for entity matching from the next collection run
    onwards" -> the accept response's `artist.terms` is asserted to be exactly the corrected
    set — the guessed short name is gone, the guessed handle's casing was corrected in place,
    and the new variant/handle are present.
  - Then "the title appears in my read-only list" -> `GET /me/titles` as the acceptor lists it.

Budget spends the seven further tests where this story is most likely to be wrong:

  - Section 2 — the behaviour the module docstring calls out by name: preview must be
    read-only and must not consume the invitation, checked by previewing twice and then
    still successfully accepting on the same token.
  - Section 3 — the error path the story's Notes imply but the scenario does not narrate: a
    handle-only invitation (no `invited_email`) can never be verified as reaching the right
    person, so acceptance must refuse it outright rather than let a verified stranger claim it.
  - Section 4 — the other half of "requires the caller's email to be verified AND to match":
    an unverified account holding the exactly-right, correctly-addressed token must still be
    refused.
  - Section 5 — the boundary explicitly named in the brief: an artist entity already linked to
    a different account cannot be claimed by a second invitation for the same entity, and the
    failed attempt must leave the first account's claim and the second membership's pending
    state untouched.
  - Section 6 — the empty-data case the "add, correct, or remove" clause implies a limit on:
    confirming a set with nothing in it (every guess removed, nothing added) must be rejected,
    not accepted as "no identity to match on".
  - Section 7 — the legitimate branch `TitleInvitationService._claim_artist` carves out of the
    conditional-UPDATE claim (reviewer finding #1): the same account accepting a second
    invitation that resolves to the same artist entity — a real flow, tagged on two titles in
    one organization — must still succeed, not be mistaken for someone else's conflicting claim.
  - Section 8 — the NFKC-expansion bound reviewer finding #2 added to `_build_confirmed_terms`:
    a handle `platform` that clears Pydantic's 40-character `max_length` as typed but expands
    past it once normalised must be refused as a 422, not written and left to overflow the
    column on Postgres as a 500. Mirrors Section 9 of test_tag_artist_on_title_and_invite.py.
"""

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Artist, TitleMembership, User
from app.services.title_invitation_service import (
    ALREADY_CLAIMED_MESSAGE,
    NO_IDENTITY_MESSAGE,
    PRIVACY_NOTICE,
    UNVERIFIABLE_INVITATION_MESSAGE,
    UNVERIFIED_EMAIL_MESSAGE,
)

ORGANIZATIONS_URL = "/api/v1/organizations"
PREVIEW_URL = "/api/v1/titles/invitations/preview"
ACCEPT_URL = "/api/v1/titles/invitations/accept"
ME_TITLES_URL = "/api/v1/me/titles"

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


def _tag_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/tagged-artists"


def _memberships_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/memberships"


def _title_payload(**overrides: Any) -> dict[str, Any]:
    return {**DEFAULT_TITLE_PAYLOAD, **overrides}


async def _create_organization(client: AsyncClient, name: str = "Sun Pictures") -> str:
    response = await client.post(
        ORGANIZATIONS_URL,
        json={
            "name": name,
            "slug": name.lower().replace(" ", "-"),
            "organization_type": "production_house",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_title(client: AsyncClient, organization_id: str, payload: dict[str, Any]) -> str:
    response = await client.post(_titles_url(organization_id), json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_title_with_cast(client: AsyncClient, *, cast: list[str]) -> tuple[str, str]:
    organization_id = await _create_organization(client)
    title_id = await _create_title(client, organization_id, _title_payload(lead_cast=cast))
    return organization_id, title_id


async def _tag(
    client: AsyncClient,
    title_id: str,
    *,
    artist_name: str,
    contact_email: str | None = None,
    contact_handle: str | None = None,
    name_variants: list[str] | None = None,
    handles: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"artist_name": artist_name}
    if contact_email is not None:
        payload["contact_email"] = contact_email
    if contact_handle is not None:
        payload["contact_handle"] = contact_handle
    if name_variants is not None:
        payload["name_variants"] = name_variants
    if handles is not None:
        payload["handles"] = handles
    response = await client.post(_tag_url(title_id), json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _create_user(
    db_session: AsyncSession, *, email: str, display_name: str, is_email_verified: bool = True
) -> User:
    user = User(email=email, display_name=display_name, is_email_verified=is_email_verified)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _as(client: AsyncClient, user: User) -> AsyncClient:
    client.headers["X-User-Id"] = str(user.id)
    return client


def _terms_set(artist_json: dict[str, Any]) -> set[tuple[str, str, str | None]]:
    return {
        (term["term_type"], term["normalized_value"], term["platform"])
        for term in artist_json["terms"]
    }


# ---------------------------------------------------------------------------
# Section 1 — The one Gherkin scenario, end to end.
# ---------------------------------------------------------------------------


async def test_artist_accepts_title_invitation_and_confirms_corrected_identity_set(
    api_client: AsyncClient, unauthenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    # Given: a production house has tagged me on a title and sent me an invitation, and the
    # acceptance flow will pre-fill the name variants and handles it entered for me.
    _, title_id = await _create_title_with_cast(api_client, cast=["Anirudh Ravichandran"])
    tagged = await _tag(
        api_client,
        title_id,
        artist_name="Anirudh Ravichandran",
        contact_email="anirudh@example.com",
        name_variants=["Anirudh R"],
        handles=[{"platform": "instagram", "handle": "anirudh_official"}],
    )
    raw_token = tagged["token"]

    artist_user = await _create_user(
        db_session, email="anirudh@example.com", display_name="Anirudh Ravichandran"
    )
    artist_client = _as(unauthenticated_client, artist_user)

    preview = await artist_client.post(PREVIEW_URL, json={"token": raw_token})
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["title_name"] == "Nova"
    assert preview_body["organization_name"] == "Sun Pictures"
    assert preview_body["artist_display_name"] == "Anirudh Ravichandran"
    assert preview_body["invited_email"] == "anirudh@example.com"
    assert set(preview_body["name_variants"]) == {"Anirudh Ravichandran", "Anirudh R"}
    assert preview_body["handles"] == [{"platform": "instagram", "handle": "anirudh_official"}]
    # Given: the flow explains that the production house cannot see my personal dashboard.
    assert preview_body["privacy_notice"] == PRIVACY_NOTICE

    # When: I accept the invitation and confirm my corrected identity set -- Given: I can
    # add, correct, or remove any pre-filled variant before confirming. "Anirudh R" is
    # removed outright; "anirudh_official" is corrected in place (same identity, different
    # casing); "AnirudhRavichander" and a twitter handle are added, neither of which the
    # production house ever typed.
    accept_response = await artist_client.post(
        ACCEPT_URL,
        json={
            "token": raw_token,
            "name_variants": ["Anirudh Ravichandran", "AnirudhRavichander"],
            "handles": [
                {"platform": "instagram", "handle": "Anirudh_Official"},
                {"platform": "twitter", "handle": "AnirudhOfficial"},
            ],
        },
    )
    assert accept_response.status_code == 200, accept_response.text
    accepted = accept_response.json()
    assert accepted["status"] == "active"

    # Then: the corrected variants are used for entity matching from the next collection
    # run onwards -- the removed guess is gone, the corrected handle kept its identity slot
    # but with the artist's casing, and both new entries are present. Nothing beyond this
    # set survives.
    assert _terms_set(accepted["artist"]) == {
        ("name_variant", "anirudh ravichandran", None),
        ("name_variant", "anirudhravichander", None),
        ("handle", "anirudh_official", "instagram"),
        ("handle", "anirudhofficial", "twitter"),
    }
    corrected_instagram_term = next(
        term for term in accepted["artist"]["terms"] if term["platform"] == "instagram"
    )
    assert corrected_instagram_term["value"] == "Anirudh_Official"

    # Then: my artist entity is linked to my account. Not exposed on `ArtistRead`, so read
    # it back from the database directly.
    artist_row = await db_session.get(Artist, uuid.UUID(accepted["artist"]["id"]))
    assert artist_row is not None
    assert artist_row.linked_user_id == artist_user.id

    membership_row = await db_session.get(TitleMembership, uuid.UUID(accepted["id"]))
    assert membership_row is not None
    assert membership_row.subject_user_id == artist_user.id

    # Then: the title appears in my read-only list.
    shared_titles = await artist_client.get(ME_TITLES_URL)
    assert shared_titles.status_code == 200, shared_titles.text
    assert [title["id"] for title in shared_titles.json()] == [title_id]


# ---------------------------------------------------------------------------
# Section 2 — Preview is read-only and must not consume the invitation.
# ---------------------------------------------------------------------------


async def test_previewing_an_invitation_repeatedly_does_not_consume_it(
    api_client: AsyncClient, unauthenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, title_id = await _create_title_with_cast(api_client, cast=["Real Lead Actor"])
    tagged = await _tag(
        api_client, title_id, artist_name="Real Lead Actor", contact_email="star@example.com"
    )
    raw_token = tagged["token"]

    artist_user = await _create_user(db_session, email="star@example.com", display_name="Star")
    artist_client = _as(unauthenticated_client, artist_user)

    first_preview = await artist_client.post(PREVIEW_URL, json={"token": raw_token})
    second_preview = await artist_client.post(PREVIEW_URL, json={"token": raw_token})
    assert first_preview.status_code == 200, first_preview.text
    assert second_preview.status_code == 200, second_preview.text
    assert first_preview.json() == second_preview.json()

    # The membership is still pending after two previews -- a prefetching client opening
    # the link could not have silently accepted on the artist's behalf.
    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.json()["memberships"][0]["status"] == "pending"

    # The token is still redeemable -- previewing did not burn it.
    accept_response = await artist_client.post(
        ACCEPT_URL, json={"token": raw_token, "name_variants": ["Real Lead Actor"], "handles": []}
    )
    assert accept_response.status_code == 200, accept_response.text


# ---------------------------------------------------------------------------
# Section 3 — Error path: a handle-only invitation cannot be verified and must be refused.
# ---------------------------------------------------------------------------


async def test_accepting_a_handle_only_invitation_is_refused_as_unverifiable(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    _, title_id = await _create_title_with_cast(api_client, cast=["Real Lead Actor"])
    tagged = await _tag(
        api_client, title_id, artist_name="Real Lead Actor", contact_handle="@real_lead_actor"
    )
    raw_token = tagged["token"]

    # `other_api_client` is a verified account -- verification alone must not be enough
    # when there was never an email to check it against.
    response = await other_api_client.post(
        ACCEPT_URL, json={"token": raw_token, "name_variants": ["Real Lead Actor"], "handles": []}
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "PermissionDeniedError"
    assert UNVERIFIABLE_INVITATION_MESSAGE in response.text

    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.json()["memberships"][0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Section 4 — Error path: an unverified account is refused even with the exactly-right,
# correctly-addressed token.
# ---------------------------------------------------------------------------


async def test_accepting_with_an_unverified_email_is_refused(
    api_client: AsyncClient, unauthenticated_client: AsyncClient, unverified_user: User
) -> None:
    _, title_id = await _create_title_with_cast(api_client, cast=["Real Lead Actor"])
    tagged = await _tag(
        api_client, title_id, artist_name="Real Lead Actor", contact_email=unverified_user.email
    )
    raw_token = tagged["token"]

    unverified_client = _as(unauthenticated_client, unverified_user)
    response = await unverified_client.post(
        ACCEPT_URL, json={"token": raw_token, "name_variants": ["Real Lead Actor"], "handles": []}
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "PermissionDeniedError"
    assert UNVERIFIED_EMAIL_MESSAGE in response.text

    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.json()["memberships"][0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Section 5 — Boundary: an artist entity already linked to a different account cannot be
# claimed by a second invitation.
# ---------------------------------------------------------------------------


async def test_an_artist_already_linked_to_a_different_account_cannot_be_claimed(
    api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
    db_session: AsyncSession,
) -> None:
    organization_id = await _create_organization(api_client)
    # Same organization, same cast name on two titles -- `_resolve_artist` reuses one
    # artist row for both, so both memberships end up pointing at the same entity.
    title_a = await _create_title(
        api_client, organization_id, _title_payload(name="Nova", lead_cast=["Anirudh Ravichandran"])
    )
    title_b = await _create_title(
        api_client,
        organization_id,
        _title_payload(name="Nova Two", lead_cast=["Anirudh Ravichandran"]),
    )
    tagged_a = await _tag(
        api_client,
        title_a,
        artist_name="Anirudh Ravichandran",
        contact_email="anirudh@example.com",
    )
    tagged_b = await _tag(
        api_client,
        title_b,
        artist_name="Anirudh Ravichandran",
        contact_email=other_pilot_user.email,
    )
    assert tagged_a["artist"]["id"] == tagged_b["artist"]["id"]

    artist_user = await _create_user(
        db_session, email="anirudh@example.com", display_name="Anirudh Ravichandran"
    )
    artist_client = _as(unauthenticated_client, artist_user)
    first_accept = await artist_client.post(
        ACCEPT_URL,
        json={"token": tagged_a["token"], "name_variants": ["Anirudh Ravichandran"], "handles": []},
    )
    assert first_accept.status_code == 200, first_accept.text

    # `other_pilot_user` is a distinct, verified account whose email correctly matches the
    # second membership's `invited_email` -- everything about their claim is legitimate
    # except that the entity is already someone else's.
    second_accept = await other_api_client.post(
        ACCEPT_URL,
        json={"token": tagged_b["token"], "name_variants": ["Anirudh Ravichandran"], "handles": []},
    )

    assert second_accept.status_code == 409, second_accept.text
    assert second_accept.json()["code"] == "ResourceConflictError"
    assert ALREADY_CLAIMED_MESSAGE in second_accept.text

    artist_row = await db_session.get(Artist, uuid.UUID(tagged_a["artist"]["id"]))
    assert artist_row is not None
    assert artist_row.linked_user_id == artist_user.id

    members_view = await api_client.get(_memberships_url(title_b))
    membership_b = next(m for m in members_view.json()["memberships"] if m["id"] == tagged_b["id"])
    assert membership_b["status"] == "pending"


# ---------------------------------------------------------------------------
# Section 6 — Empty-data case: confirming a set with nothing in it is rejected, not
# accepted as "no identity to match on".
# ---------------------------------------------------------------------------


async def test_confirming_an_empty_identity_set_is_rejected(
    api_client: AsyncClient, unauthenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, title_id = await _create_title_with_cast(api_client, cast=["Real Lead Actor"])
    tagged = await _tag(
        api_client, title_id, artist_name="Real Lead Actor", contact_email="star@example.com"
    )
    raw_token = tagged["token"]

    artist_user = await _create_user(db_session, email="star@example.com", display_name="Star")
    artist_client = _as(unauthenticated_client, artist_user)

    # Nothing confirmed -- not even the artist's own name, which `tag_artist` always seeds
    # as a name variant. There is no way to "add, correct, or remove" down to zero.
    response = await artist_client.post(
        ACCEPT_URL, json={"token": raw_token, "name_variants": [], "handles": []}
    )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "ValidationFailedError"
    assert NO_IDENTITY_MESSAGE in response.text

    # Nothing was written: the membership is still pending and the artist's original,
    # production-house-entered identity set is untouched.
    members_view = await api_client.get(_memberships_url(title_id))
    membership = members_view.json()["memberships"][0]
    assert membership["status"] == "pending"
    assert _terms_set(membership["artist"]) == {("name_variant", "real lead actor", None)}


# ---------------------------------------------------------------------------
# Section 7 — Regression (reviewer finding #1): the same account accepting a second
# invitation for the same artist entity is the legitimate branch of the conditional-UPDATE
# claim, not a conflict. `ArtistRepository.claim_for_user`'s WHERE clause only matches when
# `linked_user_id IS NULL`, so the second accept's UPDATE necessarily matches zero rows --
# `_claim_artist` must read that as "already mine" via `get_linked_to_user`, not as
# "someone else got there first". Getting this branch backwards would break a real flow:
# an actor tagged on two titles for the same production house.
# ---------------------------------------------------------------------------


async def test_the_same_account_accepting_a_second_invitation_for_the_same_artist_succeeds(
    api_client: AsyncClient, unauthenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)
    # Same organization, same cast name on two titles -- `_resolve_artist` reuses one
    # artist row for both, so both memberships point at the same entity.
    title_a = await _create_title(
        api_client, organization_id, _title_payload(name="Nova", lead_cast=["Anirudh Ravichandran"])
    )
    title_b = await _create_title(
        api_client,
        organization_id,
        _title_payload(name="Nova Two", lead_cast=["Anirudh Ravichandran"]),
    )
    tagged_a = await _tag(
        api_client,
        title_a,
        artist_name="Anirudh Ravichandran",
        contact_email="anirudh@example.com",
    )
    tagged_b = await _tag(
        api_client,
        title_b,
        artist_name="Anirudh Ravichandran",
        contact_email="anirudh@example.com",
    )
    assert tagged_a["artist"]["id"] == tagged_b["artist"]["id"]

    artist_user = await _create_user(
        db_session, email="anirudh@example.com", display_name="Anirudh Ravichandran"
    )
    artist_client = _as(unauthenticated_client, artist_user)

    first_accept = await artist_client.post(
        ACCEPT_URL,
        json={"token": tagged_a["token"], "name_variants": ["Anirudh Ravichandran"], "handles": []},
    )
    assert first_accept.status_code == 200, first_accept.text

    # Same account, second title, same artist entity -- `claim_for_user`'s conditional
    # UPDATE necessarily matches zero rows here because `linked_user_id` is already set,
    # but it is already set to *this* account, so this must succeed rather than be read as
    # a conflict.
    second_accept = await artist_client.post(
        ACCEPT_URL,
        json={"token": tagged_b["token"], "name_variants": ["Anirudh Ravichandran"], "handles": []},
    )
    assert second_accept.status_code == 200, second_accept.text
    assert second_accept.json()["status"] == "active"

    artist_row = await db_session.get(Artist, uuid.UUID(tagged_a["artist"]["id"]))
    assert artist_row is not None
    assert artist_row.linked_user_id == artist_user.id

    # Both memberships are now this account's, and both titles show up in their read-only
    # list.
    shared_titles = await artist_client.get(ME_TITLES_URL)
    assert shared_titles.status_code == 200, shared_titles.text
    assert {title["id"] for title in shared_titles.json()} == {title_a, title_b}


# ---------------------------------------------------------------------------
# Section 8 — Regression (reviewer finding #2): a handle `platform` that clears Pydantic's
# 40-character `max_length` as typed but expands past it under NFKC must be a 422 from
# `_build_confirmed_terms`'s `ensure_fits` call, not a 500 from an oversized INSERT.
# Mirrors test_tag_artist_on_title_and_invite.py Section 9, which asserts the same bound on
# the tagging path. SQLite does not enforce VARCHAR limits, so this asserts the service's
# own bound rather than the column's.
# ---------------------------------------------------------------------------


async def test_accepting_with_a_platform_that_expands_past_the_length_bound_is_rejected(
    api_client: AsyncClient, unauthenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    # "ﬃ" is one character on the way in and three ("ffi") after NFKC, so 14 of them clear
    # Pydantic's 40-character `max_length` on `platform` as typed (14 <= 40) and become 42
    # stored characters -- past `ARTIST_PLATFORM_MAX_LENGTH`.
    ligature_platform = "ﬃ" * 14
    assert len(ligature_platform) <= 40

    _, title_id = await _create_title_with_cast(api_client, cast=["Real Lead Actor"])
    tagged = await _tag(
        api_client, title_id, artist_name="Real Lead Actor", contact_email="star@example.com"
    )
    raw_token = tagged["token"]

    artist_user = await _create_user(db_session, email="star@example.com", display_name="Star")
    artist_client = _as(unauthenticated_client, artist_user)

    response = await artist_client.post(
        ACCEPT_URL,
        json={
            "token": raw_token,
            "name_variants": ["Real Lead Actor"],
            "handles": [{"platform": ligature_platform, "handle": "star_official"}],
        },
    )

    assert response.status_code == 422, response.text

    # Nothing was written: the membership is still pending and the artist's original,
    # production-house-entered identity set is untouched.
    members_view = await api_client.get(_memberships_url(title_id))
    membership = members_view.json()["memberships"][0]
    assert membership["status"] == "pending"
    assert _terms_set(membership["artist"]) == {("name_variant", "real lead actor", None)}

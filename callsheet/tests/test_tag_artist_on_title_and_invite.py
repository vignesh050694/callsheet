"""Tests for E01-S03 — Tag a cast member on a title and invite them.

Story: stories/E01-organizations-access-membership/E01-S03-tag-artist-on-title-and-invite.md

The story has exactly one Gherkin scenario ("Owner tags the lead actor on a title and
invites them"), covered end to end by the single test in Section 1. Its Given/When/Then
clauses map onto that one test as follows:

  - Given "I own a title that has an active collection running" -> the title is created
    through the real setup endpoint (which, per E03-S01, always auto-queues a first
    collection run), and the collection status is read back to confirm a run is owed.
  - Given "the title's cast list includes the actor I want to tag" -> the title is created
    with the actor on `lead_cast`.
  - Given "the artist has an email address ... I can send an invitation to" -> the tag
    payload carries `contact_email`.
  - Given "the tagging screen states that a tagged artist sees only mentions of the title
    that also mention them" -> asserted against the returned `scope` object.
  - When "I tag the actor ... and send the invitation" -> the POST to
    `/titles/{id}/tagged-artists`.
  - Then "the actor receives an invitation" -> `InvitationNotifier.send_title_invitation` is
    asserted called, the same seam E01-S02's suite uses for the analogous claim.
  - Then "a pending 'tagged artist' membership appears on the title showing the restricted
    scope" -> both the create response and a follow-up `GET .../memberships` are checked.

Budget spends the five further tests where this story is most likely to be wrong:

  - Section 2 — the boundary the story's own Given implies: tagging someone *not* on the
    cast list must be refused, not silently create a stranger's entry.
  - Section 3 — the other Given-implied boundary: no reachable contact channel at all.
  - Section 4 — the error path around double-tagging the same person (a double-submit, or
    the same actor re-typed with different casing) must be a conflict, not a second row.
  - Section 5 — the Notes' explicit claim: untagging removes the membership outright (not
    merely marks it revoked) and access is reversible — re-tagging afterwards must work.
  - Section 6 — a text/encoding boundary the implementation's own comments call out by
    name (`joiner_folded`, the ZWNJ/ZWJ handling `app/core/identity_terms.py` documents for
    exactly this multilingual corpus): a cast-list name and a tag-form name that differ only
    by an invisible zero-width joiner must still be recognised as the same person, exercised
    here through the real HTTP path rather than at the helper-function level.
"""

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TitleMembership, User
from app.schemas.title_membership import NO_CONTACT_MESSAGE
from app.services.invitation_notifier import InvitationNotifier

ORGANIZATIONS_URL = "/api/v1/organizations"
INVITATIONS_URL = "/api/v1/invitations"
ACCEPT_URL = f"{INVITATIONS_URL}/accept"
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


def _tag_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/tagged-artists"


def _memberships_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/memberships"


def _membership_url(title_id: str, membership_id: str) -> str:
    return f"/api/v1/titles/{title_id}/memberships/{membership_id}"


def _invite_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/invitations"


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


async def _create_title_with_cast(client: AsyncClient, *, cast: list[str]) -> tuple[str, str]:
    """A title owned by `client`'s caller, with `cast` on `lead_cast`. Returns
    (organization_id, title_id)."""
    organization_id = await _create_organization(client)
    title_id = await _create_title(client, organization_id, _title_payload(lead_cast=cast))
    return organization_id, title_id


async def _tag(
    client: AsyncClient,
    title_id: str,
    *,
    artist_name: str,
    contact_email: str | None = "star@example.com",
    contact_handle: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"artist_name": artist_name}
    if contact_email is not None:
        payload["contact_email"] = contact_email
    if contact_handle is not None:
        payload["contact_handle"] = contact_handle
    response = await client.post(_tag_url(title_id), json=payload)
    return response


async def _invite(
    client: AsyncClient, organization_id: str, email: str, role: str = "viewer"
) -> dict[str, Any]:
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

    Mirrors the pattern in `test_create_title_with_rich_identity.py`.
    """
    invitation = await _invite(owner_client, organization_id, email, "viewer")
    await _accept(viewer_client, invitation["token"])


# ---------------------------------------------------------------------------
# Section 1 — The one Gherkin scenario, end to end.
# ---------------------------------------------------------------------------


async def test_owner_tags_lead_actor_and_sends_invitation_creating_pending_restricted_membership(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_send = AsyncMock()
    monkeypatch.setattr(InvitationNotifier, "send_title_invitation", mock_send)

    # Given: I own a title (whose cast list includes the actor) that has an active
    # collection running -- title setup always auto-queues a first run (E03-S01).
    _, title_id = await _create_title_with_cast(api_client, cast=["Anirudh Ravichandran"])
    collection_status = await api_client.get(f"/api/v1/titles/{title_id}/collection")
    assert collection_status.status_code == 200
    assert collection_status.json()["next_run_at"] is not None

    # When: I tag the actor on the title and send the invitation, with a reachable
    # contact channel (Given: an email address I can send an invitation to).
    response = await _tag(
        api_client,
        title_id,
        artist_name="Anirudh Ravichandran",
        contact_email="anirudh@example.com",
    )

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["role"] == "tagged_artist"
    assert created["status"] == "pending"
    assert created["artist"]["display_name"] == "Anirudh Ravichandran"
    assert created["invited_email"] == "anirudh@example.com"
    assert created["token"]
    # Given: the tagging screen states a tagged artist sees only mentions naming them.
    assert created["scope"]["can_see_only_mentions_naming_subject"] is True
    assert created["scope"]["can_edit_title_setup"] is False

    # Then: the actor receives an invitation.
    mock_send.assert_awaited_once()
    sent_membership = mock_send.await_args.args[0]
    assert sent_membership.invited_email == "anirudh@example.com"
    assert mock_send.await_args.args[2] == "Anirudh Ravichandran"

    # Then: a pending "tagged artist" membership appears on the title, restricted scope
    # and all.
    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.status_code == 200
    memberships = members_view.json()["memberships"]
    assert len(memberships) == 1
    assert memberships[0]["status"] == "pending"
    assert memberships[0]["role"] == "tagged_artist"
    assert memberships[0]["scope"]["can_see_only_mentions_naming_subject"] is True


# ---------------------------------------------------------------------------
# Section 2 — Boundary: the tagged person must already be on the title's cast list.
# ---------------------------------------------------------------------------


async def test_tagging_someone_not_on_the_titles_cast_list_is_rejected(
    api_client: AsyncClient,
) -> None:
    _, title_id = await _create_title_with_cast(api_client, cast=["Real Lead Actor"])

    response = await _tag(api_client, title_id, artist_name="Some Stranger")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "ValidationFailedError"

    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.json()["memberships"] == []


# ---------------------------------------------------------------------------
# Section 3 — Boundary: there must be a reachable contact channel.
# ---------------------------------------------------------------------------


async def test_tagging_without_email_or_handle_is_rejected(api_client: AsyncClient) -> None:
    _, title_id = await _create_title_with_cast(api_client, cast=["Real Lead Actor"])

    response = await _tag(api_client, title_id, artist_name="Real Lead Actor", contact_email=None)

    assert response.status_code == 422, response.text

    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.json()["memberships"] == []


# ---------------------------------------------------------------------------
# Section 4 — Error path: tagging the same person twice is a conflict, not a second row.
# ---------------------------------------------------------------------------


async def test_tagging_the_same_actor_twice_returns_conflict_not_a_second_membership(
    api_client: AsyncClient,
) -> None:
    _, title_id = await _create_title_with_cast(api_client, cast=["Anirudh Ravichandran"])
    first = await _tag(
        api_client,
        title_id,
        artist_name="Anirudh Ravichandran",
        contact_email="first@example.com",
    )
    assert first.status_code == 201, first.text

    # Re-typed with different casing/whitespace and a different contact -- still the same
    # person by the normalized-name identity the artist row is keyed on.
    second = await _tag(
        api_client,
        title_id,
        artist_name="  ANIRUDH   RAVICHANDRAN  ",
        contact_email="second@example.com",
    )

    assert second.status_code == 409, second.text
    assert second.json()["code"] == "ResourceConflictError"

    members_view = await api_client.get(_memberships_url(title_id))
    assert len(members_view.json()["memberships"]) == 1


# ---------------------------------------------------------------------------
# Section 5 — Notes: untagging removes the membership outright (not merely revokes it),
# and the tag is reversible -- re-tagging afterwards must succeed.
# ---------------------------------------------------------------------------


async def test_untagging_removes_membership_outright_and_permits_re_tagging(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, title_id = await _create_title_with_cast(api_client, cast=["Anirudh Ravichandran"])
    created = await _tag(
        api_client,
        title_id,
        artist_name="Anirudh Ravichandran",
        contact_email="anirudh@example.com",
    )
    assert created.status_code == 201, created.text
    membership_id = created.json()["id"]

    delete_response = await api_client.delete(_membership_url(title_id, membership_id))
    assert delete_response.status_code == 204

    # The row is gone outright -- not merely marked revoked -- per the Notes ("untagging
    # removes the membership").
    row = await db_session.get(TitleMembership, uuid.UUID(membership_id))
    assert row is None

    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.json()["memberships"] == []

    # Reversible: re-tagging the same actor immediately afterwards succeeds rather than
    # colliding with the deleted row.
    re_tagged = await _tag(
        api_client,
        title_id,
        artist_name="Anirudh Ravichandran",
        contact_email="anirudh-again@example.com",
    )
    assert re_tagged.status_code == 201, re_tagged.text

    members_view_after = await api_client.get(_memberships_url(title_id))
    memberships_after = members_view_after.json()["memberships"]
    assert len(memberships_after) == 1
    assert memberships_after[0]["status"] == "pending"
    assert memberships_after[0]["id"] != membership_id


# ---------------------------------------------------------------------------
# Section 6 — Text/encoding boundary: a cast-list name and a tag-form name that differ
# only by an invisible zero-width non-joiner must still match. `app/core/identity_terms.py`
# names this exact hazard ("a hashtag copied between apps routinely picks one up or loses
# one") and `TitleMembershipService._ensure_named_on_title` compares on `joiner_folded`
# specifically to survive it -- checked here through the real HTTP path, not just at the
# helper-function level.
# ---------------------------------------------------------------------------


async def test_tagging_matches_the_cast_list_name_despite_a_zero_width_joiner_difference(
    api_client: AsyncClient,
) -> None:
    zwnj = "‌"
    cast_name_with_zwnj = f"தமிழ்{zwnj}சினிமா"
    tag_name_without_zwnj = "தமிழ்சினிமா"

    _, title_id = await _create_title_with_cast(api_client, cast=[cast_name_with_zwnj])

    response = await _tag(
        api_client,
        title_id,
        artist_name=tag_name_without_zwnj,
        contact_email="star@example.com",
    )

    assert response.status_code == 201, response.text
    assert response.json()["artist"]["display_name"] == tag_name_without_zwnj


# ---------------------------------------------------------------------------
# Section 7 — Regression: a `contact_handle` made up entirely of invisible characters,
# with no `contact_email`, has to be judged the same "no reachable channel" way the
# schema and the service agree on elsewhere -- a 422 naming the problem, not a 409
# "already tagged" surfaced from the `ck_title_membership_has_contact` IntegrityError
# that a handle collapsing to NULL at insert used to trip.
# ---------------------------------------------------------------------------


async def test_tagging_with_only_an_invisible_character_handle_and_no_email_is_a_validation_error(
    api_client: AsyncClient,
) -> None:
    zwnj = "‌"
    _, title_id = await _create_title_with_cast(api_client, cast=["Real Lead Actor"])

    response = await _tag(
        api_client,
        title_id,
        artist_name="Real Lead Actor",
        contact_email=None,
        contact_handle=zwnj * 3,
    )

    # Must be a validation error naming the missing contact channel, not a conflict --
    # there was never a prior tag on this title for it to collide with.
    assert response.status_code == 422, response.text
    assert response.status_code != 409
    assert NO_CONTACT_MESSAGE in response.text

    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.json()["memberships"] == []


# ---------------------------------------------------------------------------
# Section 8 — Authorization boundary on the tagging and listing routes: a non-owner
# member (viewer) may not tag (403), a non-member may not tag or list (404, the same
# "does not exist" answer a genuinely missing title would give), and a viewer -- who
# is a member, just not an owner -- may list.
# ---------------------------------------------------------------------------


async def test_viewer_cannot_tag_an_artist(
    api_client: AsyncClient, other_api_client: AsyncClient, other_pilot_user: User
) -> None:
    organization_id = await _create_organization(api_client)
    title_id = await _create_title(
        api_client, organization_id, _title_payload(lead_cast=["Real Lead Actor"])
    )
    await _make_viewer(api_client, other_api_client, organization_id, other_pilot_user.email)

    response = await _tag(other_api_client, title_id, artist_name="Real Lead Actor")

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "PermissionDeniedError"

    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.json()["memberships"] == []


async def test_non_member_cannot_tag_an_artist(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    _, title_id = await _create_title_with_cast(api_client, cast=["Real Lead Actor"])

    response = await _tag(other_api_client, title_id, artist_name="Real Lead Actor")

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_non_member_cannot_list_memberships(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    _, title_id = await _create_title_with_cast(api_client, cast=["Real Lead Actor"])
    tagged = await _tag(api_client, title_id, artist_name="Real Lead Actor")
    assert tagged.status_code == 201, tagged.text

    response = await other_api_client.get(_memberships_url(title_id))

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_viewer_can_list_memberships(
    api_client: AsyncClient, other_api_client: AsyncClient, other_pilot_user: User
) -> None:
    organization_id = await _create_organization(api_client)
    title_id = await _create_title(
        api_client, organization_id, _title_payload(lead_cast=["Real Lead Actor"])
    )
    tagged = await _tag(api_client, title_id, artist_name="Real Lead Actor")
    assert tagged.status_code == 201, tagged.text
    await _make_viewer(api_client, other_api_client, organization_id, other_pilot_user.email)

    response = await other_api_client.get(_memberships_url(title_id))

    assert response.status_code == 200, response.text
    memberships = response.json()["memberships"]
    assert len(memberships) == 1
    assert memberships[0]["role"] == "tagged_artist"


# ---------------------------------------------------------------------------
# Section 9 — Regression: a `contact_handle` that clears the schema's 300-character
# limit as typed but expands past it under NFKC has to be refused as a 422, not written.
# The tests run on SQLite, which does not enforce VARCHAR limits, so this asserts the
# bound the service applies rather than the one the column would apply on Postgres --
# where the oversized INSERT raises `DataError`, a sibling of `IntegrityError` that the
# conflict handler does not catch, surfacing an otherwise valid tag as a 500.
# ---------------------------------------------------------------------------


async def test_tagging_with_a_handle_that_expands_past_the_column_limit_is_rejected(
    api_client: AsyncClient,
) -> None:
    # "ﬃ" is one character on the way in and three after NFKC, so 150 of them clear the
    # schema's 300-character check and become 450 stored characters.
    ligature_handle = "ﬃ" * 150
    assert len(ligature_handle) <= 300
    _, title_id = await _create_title_with_cast(api_client, cast=["Real Lead Actor"])

    response = await _tag(
        api_client,
        title_id,
        artist_name="Real Lead Actor",
        contact_email=None,
        contact_handle=ligature_handle,
    )

    assert response.status_code == 422, response.text
    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.json()["memberships"] == []

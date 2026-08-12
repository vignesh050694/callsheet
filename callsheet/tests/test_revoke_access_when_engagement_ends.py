"""Tests for E01-S06 — Revoke a partner's access the day the engagement ends.

Story: stories/E01-organizations-access-membership/E01-S06-revoke-access-when-engagement-ends.md

The story has exactly one Gherkin scenario ("Owner revokes an agency membership while the
agency has the dashboard open"), covered end to end by the single test in Section 1. Its
Given/When/Then clauses map onto that one test as follows:

  - Given "an agency organization currently has manager access to one of my titles" -> the
    owner shares a title with an agency organization via POST /titles/{id}/shares.
  - Given "an agency user has that title's dashboard open in their browser" -> stood in for
    by a successful GET of the title and the client switcher as the agency, *before*
    revocation -- that is what "already open" means for an HTTP API: whatever the last
    successful read returned, since nothing about revocation can reach into a browser tab.
  - Given "the Members screen shows a 'Revoke access' action for each external membership"
    -> the owner's own GET .../memberships carries the membership id the revoke call below
    targets.
  - Given "revocation is confirmed with a dialog naming the organization losing access" ->
    the same member-list read carries the agency's name, which is what such a dialog would
    show; this is a UI concern with no further server-side behaviour to assert.
  - When "I confirm the revocation" -> POST /titles/{id}/memberships/{membership_id}/revoke.
  - Then "the agency user's next request fails authorization and they are returned to their
    client list with the title gone" -> GET /titles/{id} and GET /me/titles, both as the
    agency, are re-checked after revocation.
  - Then "...with the revocation recorded in the access audit log" -> GET
    /titles/{id}/access-log as the owner shows a "revoked" event with actor, subject, and
    timestamp.

Budget spends the five further tests where this story is most likely to be wrong:

  - Section 2 — the Notes' claim that revocation "applies identically to tagged artists" --
    the half of that claim that is actually implemented: an *accepted* tagged-artist
    membership can be revoked exactly like an agency share, and access disappears from the
    artist's own /me/titles the same way. (The other half of that Note, internal viewers,
    is not implemented -- viewers live in a different table entirely and are out of scope
    for this story's implementation, so it is not tested here.)
  - Section 3 — double-revocation: revoking an already-revoked membership must be refused
    as a business-rule violation, not silently repeated -- two "revoked" rows for one grant
    would misreport how many times access actually changed.
  - Section 4 — re-engagement after revocation: sharing the same title with the same agency
    a second time, after a first engagement was revoked, must succeed by reactivating the
    row rather than being refused by `uq_title_membership_organization` -- and the audit
    log must read grant -> revoke -> grant in that order.
  - Section 5 — a revoked *pending* tagged-artist invitation's token must stop being
    redeemable: revoking before the artist ever accepts has to burn the link exactly like
    revoking after acceptance does.
  - Section 6 — revocation is owner-only: the agency itself, holding nothing but its own
    read-only shared grant, cannot revoke its own membership.

Out of budget and not tested here: previously exported reports are not recalled by
revocation, per the Notes -- there is no export feature in this codebase to assert
against, so this is UI-copy-only and left untested, matching the story's own framing.
"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

ORGANIZATIONS_URL = "/api/v1/organizations"
ME_TITLES_URL = "/api/v1/me/titles"
ACCEPT_URL = "/api/v1/titles/invitations/accept"

PRODUCTION_HOUSE_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}
AGENCY_PAYLOAD = {
    "name": "Orbit Media Agency",
    "slug": "orbit-media-agency",
    "organization_type": "agency",
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


def _title_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}"


def _shares_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/shares"


def _tag_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/tagged-artists"


def _memberships_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/memberships"


def _revoke_url(title_id: str, membership_id: str) -> str:
    return f"/api/v1/titles/{title_id}/memberships/{membership_id}/revoke"


def _access_log_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/access-log"


def _title_payload(**overrides: Any) -> dict[str, Any]:
    return {**DEFAULT_TITLE_PAYLOAD, **overrides}


async def _create_organization(client: AsyncClient, payload: dict[str, Any]) -> str:
    response = await client.post(ORGANIZATIONS_URL, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_title(client: AsyncClient, organization_id: str, **overrides: Any) -> str:
    response = await client.post(_titles_url(organization_id), json=_title_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _share(client: AsyncClient, title_id: str, agency_organization_id: str) -> Any:
    return await client.post(
        _shares_url(title_id), json={"agency_organization_id": agency_organization_id}
    )


async def _tag(
    client: AsyncClient, title_id: str, *, artist_name: str, contact_email: str
) -> Any:
    return await client.post(
        _tag_url(title_id), json={"artist_name": artist_name, "contact_email": contact_email}
    )


async def _create_user(db_session: AsyncSession, *, email: str, display_name: str) -> User:
    user = User(email=email, display_name=display_name, is_email_verified=True)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _as(client: AsyncClient, user: User) -> AsyncClient:
    client.headers["X-User-Id"] = str(user.id)
    return client


# ---------------------------------------------------------------------------
# Section 1 — The one Gherkin scenario, end to end.
# ---------------------------------------------------------------------------


async def test_owner_revokes_agency_membership_and_agencys_next_request_loses_the_title(
    api_client: AsyncClient, other_api_client: AsyncClient, pilot_user: User
) -> None:
    # Given: an agency organization currently has manager access to one of my titles.
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(api_client, production_house_id)
    agency_organization_id = await _create_organization(other_api_client, AGENCY_PAYLOAD)
    share_response = await _share(api_client, title_id, agency_organization_id)
    assert share_response.status_code == 201, share_response.text
    membership_id = share_response.json()["id"]

    # Given: an agency user has that title's dashboard open in their browser -- a
    # successful read before revocation, standing in for whatever is already painted on
    # their screen (which revocation cannot reach into and clear).
    pre_revoke_title = await other_api_client.get(_title_url(title_id))
    assert pre_revoke_title.status_code == 200, pre_revoke_title.text
    pre_revoke_switcher = await other_api_client.get(ME_TITLES_URL)
    assert [t["id"] for t in pre_revoke_switcher.json()] == [title_id]

    # Given: the Members screen shows a "Revoke access" action for each external
    # membership, confirmed with a dialog naming the organization losing access -- both
    # the membership id the action targets and the org name such a dialog would show are
    # available from the owner's own member list.
    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.status_code == 200, members_view.text
    membership_row = next(
        m for m in members_view.json()["memberships"] if m["id"] == membership_id
    )
    assert membership_row["subject_organization"]["name"] == AGENCY_PAYLOAD["name"]

    # When: I confirm the revocation.
    revoke_response = await api_client.post(_revoke_url(title_id, membership_id))
    assert revoke_response.status_code == 200, revoke_response.text
    assert revoke_response.json()["status"] == "revoked"

    # Then: the agency user's next request fails authorization and they are returned to
    # their client list with the title gone.
    post_revoke_title = await other_api_client.get(_title_url(title_id))
    assert post_revoke_title.status_code == 404, post_revoke_title.text
    assert post_revoke_title.json()["code"] == "ResourceNotFoundError"

    post_revoke_switcher = await other_api_client.get(ME_TITLES_URL)
    assert post_revoke_switcher.status_code == 200, post_revoke_switcher.text
    assert post_revoke_switcher.json() == []

    # Then: ... with the revocation recorded in the access audit log.
    access_log_response = await api_client.get(_access_log_url(title_id))
    assert access_log_response.status_code == 200, access_log_response.text
    revoked_event = next(
        e for e in access_log_response.json() if e["action"] == "revoked"
    )
    assert revoked_event["role"] == "agency_manager"
    # Actor: who performed the change.
    assert revoked_event["actor_user_id"] == str(pilot_user.id)
    # Subject: which organization lost access.
    assert revoked_event["subject_organization_id"] == agency_organization_id
    # Timestamp: when the change happened.
    assert revoked_event["occurred_at"] is not None


# ---------------------------------------------------------------------------
# Section 2 — The Notes' claim that revocation "applies identically to tagged artists":
# the implemented half. An accepted tagged-artist membership is revoked the same way an
# agency share is, and the artist loses the title from /me/titles immediately.
# ---------------------------------------------------------------------------


async def test_owner_revokes_an_accepted_tagged_artists_membership_same_as_an_agency(
    api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
    db_session: AsyncSession,
    pilot_user: User,
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(
        api_client, production_house_id, lead_cast=["Real Lead Actor"]
    )
    tagged = await _tag(
        api_client, title_id, artist_name="Real Lead Actor", contact_email="star@example.com"
    )
    assert tagged.status_code == 201, tagged.text
    raw_token = tagged.json()["token"]
    membership_id = tagged.json()["id"]

    artist_user = await _create_user(db_session, email="star@example.com", display_name="Star")
    artist_client = _as(unauthenticated_client, artist_user)
    accept_response = await artist_client.post(
        ACCEPT_URL,
        json={"token": raw_token, "name_variants": ["Real Lead Actor"], "handles": []},
    )
    assert accept_response.status_code == 200, accept_response.text

    # The artist can see the title before revocation.
    pre_revoke = await artist_client.get(ME_TITLES_URL)
    assert [t["id"] for t in pre_revoke.json()] == [title_id]

    revoke_response = await api_client.post(_revoke_url(title_id, membership_id))
    assert revoke_response.status_code == 200, revoke_response.text
    assert revoke_response.json()["status"] == "revoked"

    # The artist's next request loses the title, exactly like the agency's did.
    post_revoke = await artist_client.get(ME_TITLES_URL)
    assert post_revoke.json() == []
    post_revoke_title = await artist_client.get(_title_url(title_id))
    assert post_revoke_title.status_code == 404, post_revoke_title.text

    access_log_response = await api_client.get(_access_log_url(title_id))
    revoked_event = next(
        e for e in access_log_response.json() if e["action"] == "revoked"
    )
    assert revoked_event["role"] == "tagged_artist"
    assert revoked_event["actor_user_id"] == str(pilot_user.id)
    assert revoked_event["subject_user_id"] == str(artist_user.id)
    assert revoked_event["subject_organization_id"] is None


# ---------------------------------------------------------------------------
# Section 3 — Double-revocation is refused, not silently repeated: the audit log must
# not gain a second "revoked" row for one grant.
# ---------------------------------------------------------------------------


async def test_revoking_an_already_revoked_membership_is_refused_and_not_logged_twice(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(api_client, production_house_id)
    agency_organization_id = await _create_organization(other_api_client, AGENCY_PAYLOAD)
    share_response = await _share(api_client, title_id, agency_organization_id)
    assert share_response.status_code == 201, share_response.text
    membership_id = share_response.json()["id"]

    first_revoke = await api_client.post(_revoke_url(title_id, membership_id))
    assert first_revoke.status_code == 200, first_revoke.text

    second_revoke = await api_client.post(_revoke_url(title_id, membership_id))
    assert second_revoke.status_code == 422, second_revoke.text
    assert second_revoke.json()["code"] == "ValidationFailedError"

    access_log_response = await api_client.get(_access_log_url(title_id))
    revoked_events = [
        e for e in access_log_response.json() if e["action"] == "revoked"
    ]
    assert len(revoked_events) == 1


# ---------------------------------------------------------------------------
# Section 4 — Re-engagement after revocation: sharing the same title with the same
# agency again must succeed by reactivating the row, not be refused by
# `uq_title_membership_organization`, and the audit log must read grant -> revoke ->
# grant in order.
# ---------------------------------------------------------------------------


async def test_re_sharing_after_revocation_reactivates_and_audit_log_orders_grant_revoke_grant(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(api_client, production_house_id)
    agency_organization_id = await _create_organization(other_api_client, AGENCY_PAYLOAD)

    first_share = await _share(api_client, title_id, agency_organization_id)
    assert first_share.status_code == 201, first_share.text
    membership_id = first_share.json()["id"]

    revoke_response = await api_client.post(_revoke_url(title_id, membership_id))
    assert revoke_response.status_code == 200, revoke_response.text

    lost_access = await other_api_client.get(ME_TITLES_URL)
    assert lost_access.json() == []

    # Re-engagement: sharing again succeeds by reactivating the same row rather than
    # colliding with the unique constraint a returning client would otherwise trip.
    second_share = await _share(api_client, title_id, agency_organization_id)
    assert second_share.status_code == 201, second_share.text
    assert second_share.json()["id"] == membership_id
    assert second_share.json()["status"] == "active"

    regained_access = await other_api_client.get(ME_TITLES_URL)
    assert [t["id"] for t in regained_access.json()] == [title_id]

    # The audit log reads grant -> revoke -> grant, newest first.
    access_log_response = await api_client.get(_access_log_url(title_id))
    events = access_log_response.json()
    assert [e["action"] for e in events] == ["granted", "revoked", "granted"]


# ---------------------------------------------------------------------------
# Section 5 — A revoked pending tagged-artist invitation's token must stop being
# redeemable: revoking before acceptance has to burn the link exactly like revoking
# after acceptance does.
# ---------------------------------------------------------------------------


async def test_revoking_a_pending_tagged_artist_invitation_burns_its_token(
    api_client: AsyncClient, unauthenticated_client: AsyncClient, db_session: AsyncSession
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(
        api_client, production_house_id, lead_cast=["Real Lead Actor"]
    )
    tagged = await _tag(
        api_client, title_id, artist_name="Real Lead Actor", contact_email="star@example.com"
    )
    assert tagged.status_code == 201, tagged.text
    raw_token = tagged.json()["token"]
    membership_id = tagged.json()["id"]

    # Revoked while still pending -- the artist never accepted.
    revoke_response = await api_client.post(_revoke_url(title_id, membership_id))
    assert revoke_response.status_code == 200, revoke_response.text
    assert revoke_response.json()["status"] == "revoked"

    artist_user = await _create_user(db_session, email="star@example.com", display_name="Star")
    artist_client = _as(unauthenticated_client, artist_user)
    accept_response = await artist_client.post(
        ACCEPT_URL,
        json={"token": raw_token, "name_variants": ["Real Lead Actor"], "handles": []},
    )

    # The token in the artist's inbox no longer works -- indistinguishable from a token
    # that never existed.
    assert accept_response.status_code == 404, accept_response.text
    assert accept_response.json()["code"] == "ResourceNotFoundError"

    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.json()["memberships"][0]["status"] == "revoked"


# ---------------------------------------------------------------------------
# Section 6 — Revocation is owner-only: the agency holding nothing but its own
# read-only shared grant cannot revoke its own membership.
# ---------------------------------------------------------------------------


async def test_the_agency_holding_the_shared_grant_cannot_revoke_its_own_membership(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(api_client, production_house_id)
    agency_organization_id = await _create_organization(other_api_client, AGENCY_PAYLOAD)
    share_response = await _share(api_client, title_id, agency_organization_id)
    assert share_response.status_code == 201, share_response.text
    membership_id = share_response.json()["id"]

    response = await other_api_client.post(_revoke_url(title_id, membership_id))

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "PermissionDeniedError"

    # Still active -- the refused attempt changed nothing.
    unchanged = await api_client.get(_memberships_url(title_id))
    assert unchanged.json()["memberships"][0]["status"] == "active"
    # And the agency itself still has access -- refused, not silently effective.
    still_visible = await other_api_client.get(ME_TITLES_URL)
    assert [t["id"] for t in still_visible.json()] == [title_id]


# ---------------------------------------------------------------------------
# Section 7 — Regression: re-tagging a previously revoked artist shares one validation
# path with fresh tagging (`TitleMembershipService._validated_contact_handle`), so a
# contact handle that NFKC-expands past `TITLE_MEMBERSHIP_HANDLE_MAX_LENGTH` is refused
# on the revive path exactly like it is on the fresh-tag path -- it used to run the
# re-tag branch before this check existed and store the over-length value with a 201.
# ---------------------------------------------------------------------------


async def test_retagging_a_revoked_artist_with_a_handle_that_expands_past_the_limit_is_rejected(
    api_client: AsyncClient,
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(
        api_client, production_house_id, lead_cast=["Real Lead Actor"]
    )
    tagged = await _tag(
        api_client, title_id, artist_name="Real Lead Actor", contact_email="star@example.com"
    )
    assert tagged.status_code == 201, tagged.text
    membership_id = tagged.json()["id"]

    revoke_response = await api_client.post(_revoke_url(title_id, membership_id))
    assert revoke_response.status_code == 200, revoke_response.text

    # "ﬃ" is one character on the way in and three after NFKC, so 150 of them clear the
    # schema's 300-character check and become 450 stored characters -- the same trap
    # tests/test_tag_artist_on_title_and_invite.py Section 9 asserts against fresh tags.
    ligature_handle = "ﬃ" * 150
    assert len(ligature_handle) <= 300

    retag_response = await api_client.post(
        _tag_url(title_id),
        json={
            "artist_name": "Real Lead Actor",
            "contact_handle": ligature_handle,
        },
    )

    assert retag_response.status_code == 422, retag_response.text

    # The revoked row must be untouched by the refused re-tag attempt -- no over-length
    # value written, and access still ended.
    members_view = await api_client.get(_memberships_url(title_id))
    membership_row = next(
        m for m in members_view.json()["memberships"] if m["id"] == membership_id
    )
    assert membership_row["status"] == "revoked"


# ---------------------------------------------------------------------------
# Section 8 — Regression: re-tagging a previously revoked artist with no contact
# channel at all -- no email, no handle -- is refused the same way a fresh tag is,
# rather than reviving the row with an unreachable invitation.
# ---------------------------------------------------------------------------


async def test_retagging_a_revoked_artist_with_no_contact_channel_is_rejected(
    api_client: AsyncClient,
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(
        api_client, production_house_id, lead_cast=["Real Lead Actor"]
    )
    tagged = await _tag(
        api_client, title_id, artist_name="Real Lead Actor", contact_email="star@example.com"
    )
    assert tagged.status_code == 201, tagged.text
    membership_id = tagged.json()["id"]

    revoke_response = await api_client.post(_revoke_url(title_id, membership_id))
    assert revoke_response.status_code == 200, revoke_response.text

    retag_response = await api_client.post(
        _tag_url(title_id), json={"artist_name": "Real Lead Actor"}
    )

    assert retag_response.status_code == 422, retag_response.text

    members_view = await api_client.get(_memberships_url(title_id))
    membership_row = next(
        m for m in members_view.json()["memberships"] if m["id"] == membership_id
    )
    assert membership_row["status"] == "revoked"


# ---------------------------------------------------------------------------
# Section 9 — Regression: `DELETE /titles/{id}/memberships/{membership_id}` (untagging)
# no longer deletes an ACCEPTED tagged-artist membership outright. Ending accepted
# access must go through the audited `revoke_access` path this story added -- untag now
# refuses with `NOT_UNTAGGABLE_MESSAGE` and the artist keeps their access.
# ---------------------------------------------------------------------------


async def test_untagging_an_accepted_membership_is_refused_and_leaves_access_intact(
    api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(
        api_client, production_house_id, lead_cast=["Real Lead Actor"]
    )
    tagged = await _tag(
        api_client, title_id, artist_name="Real Lead Actor", contact_email="star@example.com"
    )
    assert tagged.status_code == 201, tagged.text
    raw_token = tagged.json()["token"]
    membership_id = tagged.json()["id"]

    artist_user = await _create_user(db_session, email="star@example.com", display_name="Star")
    artist_client = _as(unauthenticated_client, artist_user)
    accept_response = await artist_client.post(
        ACCEPT_URL,
        json={"token": raw_token, "name_variants": ["Real Lead Actor"], "handles": []},
    )
    assert accept_response.status_code == 200, accept_response.text

    untag_response = await api_client.delete(_memberships_url(title_id) + f"/{membership_id}")

    assert untag_response.status_code == 422, untag_response.text
    assert untag_response.json()["code"] == "ValidationFailedError"

    # The refused attempt changed nothing: the membership is still active and the
    # access log carries no bypass around the audited revoke path.
    members_view = await api_client.get(_memberships_url(title_id))
    membership_row = next(
        m for m in members_view.json()["memberships"] if m["id"] == membership_id
    )
    assert membership_row["status"] == "active"

    still_visible = await artist_client.get(ME_TITLES_URL)
    assert [t["id"] for t in still_visible.json()] == [title_id]

    access_log_response = await api_client.get(_access_log_url(title_id))
    assert all(e["action"] != "revoked" for e in access_log_response.json())


# ---------------------------------------------------------------------------
# Section 10 — The legitimate case the fix must not break: untagging a still-PENDING
# tagged-artist invitation continues to work, since that is an offer nobody has taken
# up yet, not access to revoke.
# ---------------------------------------------------------------------------


async def test_untagging_a_still_pending_tag_still_works(
    api_client: AsyncClient,
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(
        api_client, production_house_id, lead_cast=["Real Lead Actor"]
    )
    tagged = await _tag(
        api_client, title_id, artist_name="Real Lead Actor", contact_email="star@example.com"
    )
    assert tagged.status_code == 201, tagged.text
    membership_id = tagged.json()["id"]

    untag_response = await api_client.delete(_memberships_url(title_id) + f"/{membership_id}")

    assert untag_response.status_code == 204, untag_response.text

    members_view = await api_client.get(_memberships_url(title_id))
    assert members_view.json()["memberships"] == []

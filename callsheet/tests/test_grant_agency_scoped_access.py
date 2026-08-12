"""Tests for E01-S05 — Grant an agency access to one title only.

Story: stories/E01-organizations-access-membership/E01-S05-grant-agency-scoped-access.md

The story has exactly one Gherkin scenario ("Owner grants an agency manager access to one
title out of several"), covered end to end by the single test in Section 1. Its
Given/When/Then clauses map onto that one test as follows:

  - Given "my organization owns three titles, two of which are unannounced" -> the owner's
    organization creates three titles; only one is ever shared.
  - Given "the agency already has its own organization on the platform" -> the agency
    organization is created up front, independently, before any sharing happens.
  - Given "the sharing screen requires me to pick specific titles rather than defaulting to
    all" -> exercised structurally: the share call names exactly one title id, and the
    other two titles are asserted unreachable afterwards -- nothing about the request shares
    more than what was named.
  - Given "the 'agency manager' role allows reading and exporting but not editing title
    setup" -> asserted against the returned `scope` object on the grant.
  - When "I share exactly one title with the agency organization" -> the POST to
    `/titles/{id}/shares`.
  - Then "the agency manager sees that single title in their client switcher" -> `GET
    /me/titles` as the agency's caller returns exactly that one title.
  - Then "and receives a 404-equivalent on any direct link to my other two titles" -> `GET
    /titles/{id}` for each of the other two titles returns 404.

Budget spends the five further tests on the story's other explicitly named requirements,
each of which is a distinct way this story could be silently wrong even with the one
scenario green:

  - Section 2 — "The agency organization must already exist AND be of type agency; sharing
    with a production house is refused" -- the wrong-type half.
  - Section 3 — the same requirement's other half: the organization must already exist.
  - Section 4 — "The role allows reading and exporting but NOT editing setup: PUT
    /titles/{id}/schedule must be 403 for the agency (not 404 -- they can see the title)."
  - Section 5 — "No lateral visibility: GET /titles/{id}/memberships and GET
    /titles/{id}/access-log must NOT be readable through a shared grant."
  - Section 6 — "Every grant writes an access audit row with actor, scope (subject) and
    timestamp."

Further coverage I would have spent budget on if it were not capped at five: (a)
authorization on the share endpoint itself -- a non-owner member of the owning
organization (a viewer) attempting to share should be refused with 403, distinct from a
stranger's 404; (b) sharing the same title with the same agency twice returns 409 rather
than a second grant; (c) sharing a title with the organization that already owns it is
refused. None of these appear in the story's own Given/When/Then or its Notes, so they
were left out under the budget rather than spent on.

---

Section 7 and 8 (added in a second round, budget of 3) cover a since-fixed reviewer
finding: `TitleMembershipService.list_memberships` used to hand-roll its own "is the
caller a member of the owning organization" check instead of going through
`TitleAccessPolicy.require_owning_organization` -- a fourth copy of the very rule the
consolidation this story's docstring in `app/services/title_access.py` describes was
meant to remove. It now calls the shared policy, like `TitleSharingService.
list_audit_events` already did. The swap is behaviour-preserving only if both the
"owning organization" half and the "shared grant" half of the old check still hold:

  - Section 7 -- the half Section 5 does not reach: an owning-organization VIEWER (not
    an owner) can still list memberships, and can still do so on a title that also has
    an active agency share sitting alongside them -- the shared grant on the *same*
    title does not widen or narrow what the viewer sees.
  - Section 8 -- the swap's own consistency risk: `list_memberships` and
    `list_audit_events` both resolve through `require_owning_organization` now, so an
    owning-organization viewer who can list memberships should be able to read the
    access log too, with the same 200 rather than the two surfaces silently diverging.
"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User

ORGANIZATIONS_URL = "/api/v1/organizations"
ME_TITLES_URL = "/api/v1/me/titles"
INVITATIONS_ACCEPT_URL = "/api/v1/invitations/accept"

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
OTHER_PRODUCTION_HOUSE_PAYLOAD = {
    "name": "Ravi Films",
    "slug": "ravi-films",
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


def _title_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}"


def _schedule_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/schedule"


def _shares_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/shares"


def _memberships_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/memberships"


def _access_log_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/access-log"


def _invitations_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/invitations"


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


async def _make_viewer(
    owner_client: AsyncClient,
    invitee_client: AsyncClient,
    organization_id: str,
    invitee_email: str,
) -> None:
    """Invites `invitee_email` as a viewer of `organization_id` and accepts on their
    behalf, so `invitee_client` ends the call as an owning-organization viewer -- the
    same pattern `test_invite_teammate_with_role.py` and
    `test_tag_artist_on_title_and_invite.py` use for the analogous case."""
    invitation = await owner_client.post(
        _invitations_url(organization_id),
        json={"email": invitee_email, "role": "viewer"},
    )
    assert invitation.status_code == 201, invitation.text
    accepted = await invitee_client.post(
        INVITATIONS_ACCEPT_URL, json={"token": invitation.json()["token"]}
    )
    assert accepted.status_code == 204, accepted.text


# ---------------------------------------------------------------------------
# Section 1 — The one Gherkin scenario, end to end.
# ---------------------------------------------------------------------------


async def test_owner_shares_one_of_three_titles_and_agency_sees_only_that_one(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    # Given: my organization owns three titles, two of which are unannounced.
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    shared_title_id = await _create_title(api_client, production_house_id, name="Nova")
    unannounced_title_id = await _create_title(api_client, production_house_id, name="Zenith")
    other_unannounced_title_id = await _create_title(api_client, production_house_id, name="Ember")

    # Given: the agency already has its own organization on the platform.
    agency_organization_id = await _create_organization(other_api_client, AGENCY_PAYLOAD)

    # When: I share exactly one title with the agency organization -- the sharing screen
    # names a specific title, not "all".
    response = await _share(api_client, shared_title_id, agency_organization_id)

    assert response.status_code == 201, response.text
    granted = response.json()
    assert granted["role"] == "agency_manager"
    assert granted["status"] == "active"
    assert granted["subject_organization"]["id"] == agency_organization_id
    # Given: the "agency manager" role allows reading and exporting but not editing setup.
    assert granted["scope"]["can_edit_title_setup"] is False
    assert granted["scope"]["can_see_only_mentions_naming_subject"] is False

    # Then: the agency manager sees that single title in their client switcher.
    client_switcher = await other_api_client.get(ME_TITLES_URL)
    assert client_switcher.status_code == 200, client_switcher.text
    visible_titles = client_switcher.json()
    assert [title["id"] for title in visible_titles] == [shared_title_id]

    # Then: ... and receives a 404-equivalent on any direct link to my other two titles.
    for other_title_id in (unannounced_title_id, other_unannounced_title_id):
        direct_link = await other_api_client.get(_title_url(other_title_id))
        assert direct_link.status_code == 404, direct_link.text
        assert direct_link.json()["code"] == "ResourceNotFoundError"


# ---------------------------------------------------------------------------
# Section 2 — The grantee must be an agency; sharing with a production house is refused.
# ---------------------------------------------------------------------------


async def test_sharing_with_a_production_house_organization_is_refused(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(api_client, production_house_id)
    other_production_house_id = await _create_organization(
        other_api_client, OTHER_PRODUCTION_HOUSE_PAYLOAD
    )

    response = await _share(api_client, title_id, other_production_house_id)

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "ValidationFailedError"

    client_switcher = await other_api_client.get(ME_TITLES_URL)
    assert client_switcher.json() == []


# ---------------------------------------------------------------------------
# Section 3 — The grantee organization must already exist.
# ---------------------------------------------------------------------------


async def test_sharing_with_a_nonexistent_organization_is_not_found(
    api_client: AsyncClient,
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(api_client, production_house_id)

    response = await _share(api_client, title_id, "00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "ResourceNotFoundError"


# ---------------------------------------------------------------------------
# Section 4 — The role reads and exports but does not edit setup: PUT .../schedule is 403
# for the agency, never 404 -- they can see the title, just not change it.
# ---------------------------------------------------------------------------


async def test_agency_manager_gets_403_not_404_editing_the_shared_titles_schedule(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(api_client, production_house_id)
    agency_organization_id = await _create_organization(other_api_client, AGENCY_PAYLOAD)
    share_response = await _share(api_client, title_id, agency_organization_id)
    assert share_response.status_code == 201, share_response.text

    # Reading is allowed -- this is genuinely a "can see, cannot change" boundary.
    read_response = await other_api_client.get(_title_url(title_id))
    assert read_response.status_code == 200, read_response.text

    schedule_response = await other_api_client.put(
        _schedule_url(title_id),
        json={"release_date": "2026-12-25", "milestones": []},
    )

    assert schedule_response.status_code == 403, schedule_response.text
    assert schedule_response.json()["code"] == "PermissionDeniedError"

    # The release date was not touched by the refused edit.
    unchanged = await api_client.get(_title_url(title_id))
    assert unchanged.json()["release_date"] == "2026-08-15"


# ---------------------------------------------------------------------------
# Section 5 — No lateral visibility: a shared grant does not open the membership list or
# the access log, even though it opens the title itself.
# ---------------------------------------------------------------------------


async def test_shared_grant_does_not_expose_memberships_or_access_log(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(api_client, production_house_id)
    agency_organization_id = await _create_organization(other_api_client, AGENCY_PAYLOAD)
    share_response = await _share(api_client, title_id, agency_organization_id)
    assert share_response.status_code == 201, share_response.text

    memberships_response = await other_api_client.get(_memberships_url(title_id))
    assert memberships_response.status_code == 404, memberships_response.text
    assert memberships_response.json()["code"] == "ResourceNotFoundError"

    access_log_response = await other_api_client.get(_access_log_url(title_id))
    assert access_log_response.status_code == 404, access_log_response.text
    assert access_log_response.json()["code"] == "ResourceNotFoundError"

    # The owner, by contrast, can read both.
    owner_memberships = await api_client.get(_memberships_url(title_id))
    assert owner_memberships.status_code == 200, owner_memberships.text
    owner_access_log = await api_client.get(_access_log_url(title_id))
    assert owner_access_log.status_code == 200, owner_access_log.text


# ---------------------------------------------------------------------------
# Section 6 — Every grant writes an access audit row with actor, scope (subject), and
# timestamp.
# ---------------------------------------------------------------------------


async def test_sharing_writes_an_access_audit_event_with_actor_subject_and_timestamp(
    api_client: AsyncClient, other_api_client: AsyncClient, pilot_user: User
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(api_client, production_house_id)
    agency_organization_id = await _create_organization(other_api_client, AGENCY_PAYLOAD)

    share_response = await _share(api_client, title_id, agency_organization_id)
    assert share_response.status_code == 201, share_response.text

    access_log_response = await api_client.get(_access_log_url(title_id))
    assert access_log_response.status_code == 200, access_log_response.text
    events = access_log_response.json()
    assert len(events) == 1
    event = events[0]
    assert event["action"] == "granted"
    assert event["role"] == "agency_manager"
    # Actor: who performed the change.
    assert event["actor_user_id"] == str(pilot_user.id)
    # Scope: which organization gained access.
    assert event["subject_organization_id"] == agency_organization_id
    assert event["subject_user_id"] is None
    # Timestamp: when the change happened.
    # The story's "timestamp" is `occurred_at`, which E01-S06 split out from `created_at`
    # so the log can order its own entries — see `app/models/access_audit.py`.
    assert event["occurred_at"] is not None


# ---------------------------------------------------------------------------
# Section 7 — Reviewer finding fixed: `list_memberships` now goes through
# `TitleAccessPolicy.require_owning_organization` instead of a hand-rolled check. Both
# halves of that policy's behaviour on the *same* title: an owning-organization viewer
# (not just an owner) can list, and the agency's shared grant on that same title still
# cannot.
# ---------------------------------------------------------------------------


async def test_owning_organization_viewer_can_list_memberships_alongside_an_agency_share(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(api_client, production_house_id)
    agency_organization_id = await _create_organization(other_api_client, AGENCY_PAYLOAD)
    share_response = await _share(api_client, title_id, agency_organization_id)
    assert share_response.status_code == 201, share_response.text

    # A colleague of the owner, invited and accepted as a viewer -- not an owner, and
    # not the agency the title was shared with.
    viewer = User(
        email="viewer@sunpictures.com",
        display_name="Sun Pictures Viewer",
        is_email_verified=True,
    )
    db_session.add(viewer)
    await db_session.commit()
    await db_session.refresh(viewer)
    unauthenticated_client.headers["X-User-Id"] = str(viewer.id)
    await _make_viewer(api_client, unauthenticated_client, production_house_id, viewer.email)

    # The viewer -- an owning-organization member, but not an owner -- can still list.
    viewer_response = await unauthenticated_client.get(_memberships_url(title_id))
    assert viewer_response.status_code == 200, viewer_response.text
    viewer_memberships = viewer_response.json()["memberships"]
    assert len(viewer_memberships) == 1
    assert viewer_memberships[0]["role"] == "agency_manager"

    # The agency's own shared grant on this same title still does not open the list.
    agency_response = await other_api_client.get(_memberships_url(title_id))
    assert agency_response.status_code == 404, agency_response.text
    assert agency_response.json()["code"] == "ResourceNotFoundError"


# ---------------------------------------------------------------------------
# Section 8 — The same policy method now backs both `list_memberships` and
# `list_audit_events` (`TitleSharingService`, which already used it). An owning-
# organization viewer who can list memberships should read the access log too --
# locking the two surfaces from silently diverging now that they share one gate.
# ---------------------------------------------------------------------------


async def test_owning_organization_viewer_can_read_access_log_same_as_memberships(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    production_house_id = await _create_organization(api_client, PRODUCTION_HOUSE_PAYLOAD)
    title_id = await _create_title(api_client, production_house_id)
    agency_organization_id = await _create_organization(other_api_client, AGENCY_PAYLOAD)
    share_response = await _share(api_client, title_id, agency_organization_id)
    assert share_response.status_code == 201, share_response.text

    viewer = User(
        email="viewer@sunpictures.com",
        display_name="Sun Pictures Viewer",
        is_email_verified=True,
    )
    db_session.add(viewer)
    await db_session.commit()
    await db_session.refresh(viewer)
    unauthenticated_client.headers["X-User-Id"] = str(viewer.id)
    await _make_viewer(api_client, unauthenticated_client, production_house_id, viewer.email)

    viewer_access_log = await unauthenticated_client.get(_access_log_url(title_id))
    assert viewer_access_log.status_code == 200, viewer_access_log.text
    events = viewer_access_log.json()
    assert len(events) == 1
    assert events[0]["action"] == "granted"

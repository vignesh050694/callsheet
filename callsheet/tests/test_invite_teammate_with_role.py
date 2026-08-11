"""Tests for E01-S02 — Invite a teammate with a role.

Story: stories/E01-organizations-access-membership/E01-S02-invite-teammate-with-role.md

The story has one Gherkin scenario ("Owner invites a publicity manager as a viewer")
whose Given/When/Then clauses are covered below, plus the two Notes, which are
testable requirements in their own right:

  - "Pending invitations are listed on the Members screen with the ability to resend
    or cancel." -> section 4.
  - "Viewer role must be enforced server-side, not only by hiding UI controls." ->
    section 6, and (for the organization resource specifically, since it is the only
    administrable resource this slice of the backend has) sections 3's
    `test_accepted_viewer_cannot_*_organization_server_side` tests.

Scope note: the Then clause "sees my organization's titles in read-only mode with no
ability to edit title setup or delete data" describes a `titles` resource that does not
exist yet in this codebase (no model, schema, or route) — it belongs to a later story/
epic. The closest available proxy for "an invited viewer gets read-only, server-enforced
access to the organization" is the organizations resource itself (GET allowed, PATCH/
DELETE refused), which is what `organization_service._ensure_caller_can_administer`
exists to enforce and what section 3 exercises. When a `titles` resource lands, this
Then clause should grow a same-shaped test against it.

Every test below is grouped under a comment naming the AC clause or Note it maps to.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invitation, Membership, MembershipRole, Organization, User
from app.services.invitation_notifier import InvitationNotifier

ORGANIZATIONS_URL = "/api/v1/organizations"
INVITATIONS_URL = "/api/v1/invitations"
ACCEPT_URL = f"{INVITATIONS_URL}/accept"

SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}


def _members_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/members"


def _invite_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/invitations"


def _resend_url(invitation_id: str) -> str:
    return f"{INVITATIONS_URL}/{invitation_id}/resend"


def _cancel_url(invitation_id: str) -> str:
    return f"{INVITATIONS_URL}/{invitation_id}"


async def _create_organization(client: AsyncClient, payload: dict = SUN_PICTURES_PAYLOAD) -> str:
    response = await client.post(ORGANIZATIONS_URL, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _invite(
    client: AsyncClient, organization_id: str, email: str, role: str = "viewer"
) -> dict:
    response = await client.post(
        _invite_url(organization_id), json={"email": email, "role": role}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _accept(client: AsyncClient, token: str) -> AsyncClient:
    return await client.post(ACCEPT_URL, json={"token": token})


# ---------------------------------------------------------------------------
# Section 1 — Given: owner, colleague's email not yet a member, roles offered
# ---------------------------------------------------------------------------


async def test_owner_invites_colleague_with_viewer_role_and_receives_single_use_token(
    api_client: AsyncClient,
) -> None:
    """Given: I am the owner. When: I enter my colleague's email, select "Viewer",
    and send the invitation. The response carries the raw token exactly once."""
    organization_id = await _create_organization(api_client)

    invitation = await _invite(api_client, organization_id, "colleague@example.com", "viewer")

    assert invitation["email"] == "colleague@example.com"
    assert invitation["role"] == "viewer"
    assert invitation["status"] == "pending"
    assert invitation["token"]


async def test_invitation_email_is_normalized_to_lowercase_on_create(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    invitation = await _invite(api_client, organization_id, "Colleague@Example.COM", "viewer")

    assert invitation["email"] == "colleague@example.com"


async def test_members_screen_accepts_owner_and_viewer_as_invite_roles(
    api_client: AsyncClient,
) -> None:
    """Given: the Members screen offers the roles "Owner" and "Viewer" — both are
    valid values the invite endpoint accepts."""
    organization_id = await _create_organization(api_client)

    viewer_invitation = await _invite(
        api_client, organization_id, "viewer-hire@example.com", "viewer"
    )
    owner_invitation = await _invite(api_client, organization_id, "owner-hire@example.com", "owner")

    assert viewer_invitation["role"] == "viewer"
    assert owner_invitation["role"] == "owner"


async def test_invite_role_must_be_owner_or_viewer(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _invite_url(organization_id),
        json={"email": "someone@example.com", "role": "editor"},
    )

    assert response.status_code == 422


async def test_invite_rejects_malformed_email(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _invite_url(organization_id),
        json={"email": "not-an-email", "role": "viewer"},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Section 2 — Given: colleague's email address is not yet a member (conflicts)
# ---------------------------------------------------------------------------


async def test_inviting_email_with_existing_pending_invitation_returns_conflict(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    await _invite(api_client, organization_id, "colleague@example.com", "viewer")

    response = await api_client.post(
        _invite_url(organization_id),
        json={"email": "colleague@example.com", "role": "viewer"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ResourceConflictError"


async def test_inviting_email_of_existing_member_returns_conflict(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
) -> None:
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")
    accept_response = await _accept(other_api_client, invitation["token"])
    assert accept_response.status_code == 204

    response = await api_client.post(
        _invite_url(organization_id),
        json={"email": other_pilot_user.email, "role": "viewer"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ResourceConflictError"


# ---------------------------------------------------------------------------
# Section 3 — When/Then: accepting grants read-only viewer access, server-enforced
# ---------------------------------------------------------------------------


async def test_accepting_invitation_creates_membership_with_invited_role_not_owner(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
    db_session: AsyncSession,
) -> None:
    """Then: on accepting, my colleague gets the role I invited them with — a viewer
    invite must not somehow make them an owner."""
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")

    response = await _accept(other_api_client, invitation["token"])

    assert response.status_code == 204

    membership = (
        (
            await db_session.execute(
                select(Membership).where(
                    Membership.user_id == other_pilot_user.id,
                    Membership.organization_id == uuid.UUID(organization_id),
                )
            )
        )
        .scalars()
        .one()
    )
    assert membership.role == "viewer"


async def test_accepted_viewer_can_read_organization(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
) -> None:
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")
    await _accept(other_api_client, invitation["token"])

    response = await other_api_client.get(f"{ORGANIZATIONS_URL}/{organization_id}")

    assert response.status_code == 200


async def test_accepted_viewer_cannot_update_organization_server_side(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
    db_session: AsyncSession,
) -> None:
    """Notes: "Viewer role must be enforced server-side, not only by hiding UI
    controls." A viewer cannot edit title setup; the closest resource this backend
    slice actually has is the organization itself. PATCH must be refused with 403,
    and nothing must change."""
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")
    await _accept(other_api_client, invitation["token"])

    response = await other_api_client.patch(
        f"{ORGANIZATIONS_URL}/{organization_id}", json={"name": "Hijacked"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "PermissionDeniedError"

    organization = await db_session.get(Organization, uuid.UUID(organization_id))
    assert organization.name == "Sun Pictures"


async def test_accepted_viewer_cannot_delete_organization_server_side(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
    db_session: AsyncSession,
) -> None:
    """Notes: server-side enforcement, delete-data half. A viewer must not be able
    to delete data, and the organization must survive the attempt."""
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")
    await _accept(other_api_client, invitation["token"])

    response = await other_api_client.delete(f"{ORGANIZATIONS_URL}/{organization_id}")

    assert response.status_code == 403
    assert response.json()["code"] == "PermissionDeniedError"

    organization = await db_session.get(Organization, uuid.UUID(organization_id))
    assert organization is not None


async def test_invite_sends_notification_to_the_invited_address(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Then: my colleague receives an invitation email. The real mailer does not
    exist yet; `InvitationNotifier.send_invitation` is the seam it will replace, so
    assert against that instead."""
    mock_send = AsyncMock()
    monkeypatch.setattr(InvitationNotifier, "send_invitation", mock_send)
    organization_id = await _create_organization(api_client)

    await _invite(api_client, organization_id, "colleague@example.com", "viewer")

    mock_send.assert_awaited_once()
    sent_invitation = mock_send.await_args.args[0]
    assert sent_invitation.email == "colleague@example.com"


# ---------------------------------------------------------------------------
# Section 4 — Notes: pending invitations are listed with resend/cancel ability
# ---------------------------------------------------------------------------


async def test_members_screen_lists_members_and_pending_invitations(
    api_client: AsyncClient,
    pilot_user: User,
) -> None:
    organization_id = await _create_organization(api_client)
    await _invite(api_client, organization_id, "pending-colleague@example.com", "viewer")

    response = await api_client.get(_members_url(organization_id))

    assert response.status_code == 200
    body = response.json()
    assert [member["email"] for member in body["members"]] == [pilot_user.email]
    assert body["members"][0]["role"] == "owner"
    assert [
        invitation["email"] for invitation in body["pending_invitations"]
    ] == ["pending-colleague@example.com"]
    assert body["pending_invitations"][0]["status"] == "pending"


async def test_pending_invitation_list_item_does_not_leak_the_raw_token(
    api_client: AsyncClient,
) -> None:
    """The list endpoint must not hand back a redeemable token for every pending
    invitation on every read — only the create/resend response does, once."""
    organization_id = await _create_organization(api_client)
    await _invite(api_client, organization_id, "pending-colleague@example.com", "viewer")

    response = await api_client.get(_members_url(organization_id))

    assert "token" not in response.json()["pending_invitations"][0]


async def test_any_member_owner_or_viewer_can_view_members_screen(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
) -> None:
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")
    await _accept(other_api_client, invitation["token"])

    owner_view = await api_client.get(_members_url(organization_id))
    viewer_view = await other_api_client.get(_members_url(organization_id))

    assert owner_view.status_code == 200
    assert viewer_view.status_code == 200
    assert len(viewer_view.json()["members"]) == 2


async def test_resend_invitation_issues_new_token_and_invalidates_old_one(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
) -> None:
    """"the ability to resend" must actually re-issue the credential: the old link
    a colleague may have lost stops working, and the new one works."""
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")
    old_token = invitation["token"]

    resend_response = await api_client.post(_resend_url(invitation["id"]))
    assert resend_response.status_code == 200, resend_response.text
    new_token = resend_response.json()["token"]

    assert new_token != old_token

    old_token_attempt = await _accept(other_api_client, old_token)
    assert old_token_attempt.status_code == 404
    assert old_token_attempt.json()["code"] == "ResourceNotFoundError"

    new_token_attempt = await _accept(other_api_client, new_token)
    assert new_token_attempt.status_code == 204


async def test_cancel_invitation_makes_its_token_unusable(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
) -> None:
    """"the ability to ... cancel" must actually revoke the credential."""
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")

    cancel_response = await api_client.delete(_cancel_url(invitation["id"]))
    assert cancel_response.status_code == 204

    accept_response = await _accept(other_api_client, invitation["token"])
    assert accept_response.status_code == 404
    assert accept_response.json()["code"] == "ResourceNotFoundError"


async def test_cancel_removes_invitation_from_pending_list(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, "colleague@example.com", "viewer")

    await api_client.delete(_cancel_url(invitation["id"]))

    members_view = await api_client.get(_members_url(organization_id))
    assert members_view.json()["pending_invitations"] == []


# ---------------------------------------------------------------------------
# Section 5 — Accept: the token must be redeemable exactly once, by its addressee
# ---------------------------------------------------------------------------


async def test_accept_rejects_a_forwarded_link_to_the_wrong_recipient(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
    db_session: AsyncSession,
) -> None:
    """A forwarded invitation link must not work for anyone but the addressee.

    `accept_invitation` checks `_ensure_email_is_verified` before the wrong-recipient
    email comparison, so an *unverified* wrong recipient would be rejected by the
    verified-email branch instead — that would exercise the same status code and
    error code as the wrong-recipient branch without ever reaching it, leaving the
    "a forwarded link must not let a stranger in" property with no real coverage.
    Using `other_pilot_user` (verified, but a genuinely different email from the one
    invited) via the independent `other_api_client` isolates the wrong-recipient
    branch specifically: verification passes, so only the email mismatch can produce
    the 403 here."""
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, "addressee@example.com", "viewer")

    response = await _accept(other_api_client, invitation["token"])

    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "PermissionDeniedError"
    assert body["message"] == "This invitation was sent to a different email address"
    assert body["message"] != "Verify your email address before accepting an invitation"

    memberships = (
        (
            await db_session.execute(
                select(Membership).where(
                    Membership.user_id == other_pilot_user.id,
                    Membership.organization_id == uuid.UUID(organization_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert memberships == []


async def test_accept_unknown_token_returns_not_found(api_client: AsyncClient) -> None:
    response = await _accept(api_client, "not-a-real-token")

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_accept_already_accepted_token_returns_not_found(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
) -> None:
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")
    first_attempt = await _accept(other_api_client, invitation["token"])
    assert first_attempt.status_code == 204

    second_attempt = await _accept(other_api_client, invitation["token"])

    assert second_attempt.status_code == 404
    assert second_attempt.json()["code"] == "ResourceNotFoundError"


async def test_accept_cancelled_token_returns_not_found(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
) -> None:
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")
    await api_client.delete(_cancel_url(invitation["id"]))

    response = await _accept(other_api_client, invitation["token"])

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


# ---------------------------------------------------------------------------
# Section 6 — Notes: "Viewer role must be enforced server-side" for invite management,
# and non-members must not learn whether an organization exists (404, not 403)
# ---------------------------------------------------------------------------


async def test_non_member_inviting_returns_not_found_not_forbidden(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
) -> None:
    """A caller who is not a member at all gets the same 404 a missing organization
    id would get — a 403 here would confirm the organization exists."""
    organization_id = await _create_organization(api_client)

    response = await other_api_client.post(
        _invite_url(organization_id),
        json={"email": "someone@example.com", "role": "viewer"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_non_member_cannot_view_members_screen(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    response = await other_api_client.get(_members_url(organization_id))

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_viewer_cannot_invite_new_members(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
) -> None:
    """A viewer can see the organization (they are a member), so a refusal here is
    an honest 403, not a 404."""
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")
    await _accept(other_api_client, invitation["token"])

    response = await other_api_client.post(
        _invite_url(organization_id),
        json={"email": "someone-else@example.com", "role": "viewer"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "PermissionDeniedError"


async def test_viewer_cannot_resend_an_invitation(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
) -> None:
    organization_id = await _create_organization(api_client)
    viewer_invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")
    await _accept(other_api_client, viewer_invitation["token"])

    pending_invitation = await _invite(
        api_client, organization_id, "someone-else@example.com", "viewer"
    )

    response = await other_api_client.post(_resend_url(pending_invitation["id"]))

    assert response.status_code == 403
    assert response.json()["code"] == "PermissionDeniedError"


async def test_viewer_cannot_cancel_an_invitation(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
) -> None:
    organization_id = await _create_organization(api_client)
    viewer_invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")
    await _accept(other_api_client, viewer_invitation["token"])

    pending_invitation = await _invite(
        api_client, organization_id, "someone-else@example.com", "viewer"
    )

    response = await other_api_client.delete(_cancel_url(pending_invitation["id"]))

    assert response.status_code == 403
    assert response.json()["code"] == "PermissionDeniedError"


# ---------------------------------------------------------------------------
# Section 7 — Auth boundary: every new route requires an identified caller
# ---------------------------------------------------------------------------


async def test_unauthenticated_cannot_list_members(
    api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    response = await unauthenticated_client.get(_members_url(organization_id))

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_unauthenticated_cannot_create_invitation(
    api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    response = await unauthenticated_client.post(
        _invite_url(organization_id),
        json={"email": "someone@example.com", "role": "viewer"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_unauthenticated_cannot_resend_invitation(
    api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, "someone@example.com", "viewer")

    response = await unauthenticated_client.post(_resend_url(invitation["id"]))

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_unauthenticated_cannot_cancel_invitation(
    api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, "someone@example.com", "viewer")

    response = await unauthenticated_client.delete(_cancel_url(invitation["id"]))

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_unauthenticated_cannot_accept_invitation(
    api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, "someone@example.com", "viewer")

    response = await _accept(unauthenticated_client, invitation["token"])

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


# ---------------------------------------------------------------------------
# Section 8 — Fixes applied after review, covering the bugs a reviewer found in the
# fixed implementation. The story's Gherkin doesn't spell any of these out directly;
# they follow from the Notes ("Viewer role must be enforced server-side") and from the
# ordinary expectation that a real invitation is redeemable exactly once, by a real
# person, without leaking information a caller isn't entitled to.
# ---------------------------------------------------------------------------

# --- FIX 1a — accept_invitation: a raced membership insert returns 409, not 500 ---


async def test_accept_invitation_returns_conflict_when_membership_insert_races(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    other_pilot_user: User,
    db_session: AsyncSession,
) -> None:
    """A double-submit or two racing accepts can both pass the existing-membership
    pre-check; the (user_id, organization_id) unique constraint is the real arbiter,
    and a loser must become a 409, not an unhandled IntegrityError -> 500.

    This is a forced approximation of the race, not a real concurrency test — same
    caveat as `test_create_organization_returns_conflict_when_commit_time_insert_collides`
    in test_organization_access_control.py, whose approach this follows: the fixtures
    share one `AsyncSession` for the whole test and httpx's ASGI transport runs
    requests sequentially, so two genuinely concurrent HTTP requests cannot be produced
    here. Instead a colliding `Membership` row is added to the session but kept
    un-flushed (autoflush disabled) so `get_for_user_and_organization`'s SELECT-based
    pre-check does not see it and reports no existing membership — exactly what a real
    second writer racing the pre-check would also see. The accept request is issued
    inside the same `no_autoflush` block: `MembershipRepository.add()` calls
    `session.flush()` immediately, which is what actually issues the INSERT and is
    where the IntegrityError surfaces (not at the later `commit()`).

    This test originally caught a real implementation bug: the `except IntegrityError`
    branch called `await self._session.rollback()` and then logged
    `invitation_id=str(invitation.id)`, but `rollback()` expires every ORM object
    loaded in the session, and that synchronous attribute access on an expired
    instance tried to lazy-reload it outside of an awaited/greenlet context, raising
    `sqlalchemy.exc.MissingGreenlet` from the logging statement itself before
    `ResourceConflictError` was ever raised. That has since been fixed by reading
    `invitation.id` / `accepter.id` / `invitation.role` into locals before the try
    block. This test's own assertions have the identical hazard for the same reason —
    `other_pilot_user` is loaded in the same shared session and is expired by the same
    rollback — so the ids this test needs are captured into locals up front, below,
    before the request that triggers the rollback.
    """
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, other_pilot_user.email, "viewer")

    # Captured up front, as plain values: `accept_invitation`'s except branch calls
    # `session.rollback()`, which expires every ORM object loaded in this shared
    # session — `other_pilot_user` included. Reading `other_pilot_user.id` *after*
    # that rollback would trigger the same MissingGreenlet lazy-reload mechanism the
    # implementation bug above was made of, just relocated into the test's own
    # assertions. Mirrors the fix now applied in `accept_invitation` itself, which
    # reads `invitation.id` / `accepter.id` into locals before the try block.
    other_user_id = other_pilot_user.id
    organization_uuid = uuid.UUID(organization_id)

    with db_session.no_autoflush:
        colliding_membership = Membership(
            user_id=other_user_id,
            organization_id=organization_uuid,
            role=MembershipRole.VIEWER,
        )
        db_session.add(colliding_membership)

        response = await _accept(other_api_client, invitation["token"])

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ResourceConflictError"

    # The whole transaction rolls back together: neither the manually-added colliding
    # row nor the service's own insert survives, and the invitation is not left
    # dangling in an ACCEPTED state its membership doesn't actually reflect.
    memberships = (
        (
            await db_session.execute(
                select(Membership).where(
                    Membership.user_id == other_user_id,
                    Membership.organization_id == organization_uuid,
                )
            )
        )
        .scalars()
        .all()
    )
    assert memberships == []

    invitation_row = await db_session.get(Invitation, uuid.UUID(invitation["id"]))
    assert invitation_row.status == "pending"


# --- FIX 1b — invite_member: a colliding insert also returns 409, not 500 ---


async def test_invite_member_returns_conflict_when_token_hash_collides(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    """`invite_member` got the same try/except IntegrityError -> 409 treatment as
    `accept_invitation`, guarding `Invitation.token_hash`'s uniqueness. A real
    collision is (per the implementation's own comment) astronomically unlikely, since
    the token is 32 random bytes — there is no check-then-insert window to force here,
    only the insert itself. So this test forces the exact condition deterministically,
    by monkeypatching `generate_invitation_token` to return a fixed value for the
    duration of the test, rather than simulating concurrency: two invites minted with
    that fixed token collide on `token_hash` at insert time, and the second must come
    back as a 409, not a 500.
    """
    organization_id = await _create_organization(api_client)
    monkeypatch.setattr(
        "app.services.invitation_service.generate_invitation_token",
        lambda: "fixed-token-for-collision-test",
    )

    first = await _invite(api_client, organization_id, "first-colleague@example.com", "viewer")
    assert first["token"] == "fixed-token-for-collision-test"

    response = await api_client.post(
        _invite_url(organization_id),
        json={"email": "second-colleague@example.com", "role": "viewer"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ResourceConflictError"

    # The failed second attempt left nothing behind: only the first invitation exists.
    invitations = (await db_session.execute(select(Invitation))).scalars().all()
    assert [invitation.email for invitation in invitations] == ["first-colleague@example.com"]


# --- FIX 2 — accept_invitation: an unverified accepter is refused, even with the
# correctly-addressed invitation ---


async def test_accept_invitation_by_unverified_user_returns_forbidden(
    api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
    unverified_user: User,
) -> None:
    """Previously unchecked: accept_invitation now calls `_ensure_email_is_verified`
    before anything else, so an unverified user cannot accept even an invitation
    correctly addressed to them."""
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, unverified_user.email, "viewer")

    unauthenticated_client.headers["X-User-Id"] = str(unverified_user.id)
    response = await _accept(unauthenticated_client, invitation["token"])

    assert response.status_code == 403
    assert response.json()["code"] == "PermissionDeniedError"


# --- FIX 3 — accept_invitation: email comparison is case- and whitespace-robust ---


async def test_accept_invitation_matches_email_case_insensitively_and_ignoring_whitespace(
    api_client: AsyncClient,
    unauthenticated_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The invited email is stored normalized (lowercased, stripped) by
    `InvitationCreate.normalize_email`, but a real user's stored `email` may not be —
    it depends on however that account was created. `accept_invitation` now compares
    `accepter.email.strip().lower()` against the invitation's already-normalized email,
    so an accepter whose own record has surrounding whitespace and mixed case must
    still be recognized as the addressee."""
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, "colleague@example.com", "viewer")

    accepter = User(
        email="  Colleague@Example.com  ",
        display_name="Case Insensitive Colleague",
        is_email_verified=True,
    )
    db_session.add(accepter)
    await db_session.commit()
    await db_session.refresh(accepter)

    unauthenticated_client.headers["X-User-Id"] = str(accepter.id)
    response = await _accept(unauthenticated_client, invitation["token"])

    assert response.status_code == 204, response.text


# --- FIX 4 — _require_pending_invitation: "no such invitation" and "not your
# organization" are now indistinguishable, for both resend and cancel ---


async def test_non_member_resend_is_indistinguishable_from_a_genuinely_missing_invitation(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Before the fix, a caller holding a guessed invitation UUID could tell "no such
    invitation" apart from "real invitation, but not your organization" because the
    latter leaked the *organization's* not-found message instead of the invitation's.
    Now both paths return the identical `INVITATION_NOT_FOUND_MESSAGE`. Proven here by
    reusing the *same* invitation id for both probes — first while the invitation is
    real but foreign, then again after deleting it out from under that same id — so the
    two response bodies can be compared byte-for-byte, id included, not just by status
    code."""
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, "colleague@example.com", "viewer")
    invitation_id = invitation["id"]

    not_your_org_response = await other_api_client.post(_resend_url(invitation_id))

    invitation_row = await db_session.get(Invitation, uuid.UUID(invitation_id))
    await db_session.delete(invitation_row)
    await db_session.commit()

    genuinely_missing_response = await other_api_client.post(_resend_url(invitation_id))

    assert not_your_org_response.status_code == genuinely_missing_response.status_code == 404
    # `request_id` is per-request and expected to differ; `code` and `message` are the
    # only fields a caller could use to tell the two cases apart, and they must match.
    not_your_org_body = not_your_org_response.json()
    genuinely_missing_body = genuinely_missing_response.json()
    assert not_your_org_body["code"] == genuinely_missing_body["code"] == "ResourceNotFoundError"
    assert not_your_org_body["message"] == genuinely_missing_body["message"]


async def test_non_member_cancel_is_indistinguishable_from_a_genuinely_missing_invitation(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Same guarantee as the resend case above, for cancel."""
    organization_id = await _create_organization(api_client)
    invitation = await _invite(api_client, organization_id, "colleague@example.com", "viewer")
    invitation_id = invitation["id"]

    not_your_org_response = await other_api_client.delete(_cancel_url(invitation_id))

    invitation_row = await db_session.get(Invitation, uuid.UUID(invitation_id))
    await db_session.delete(invitation_row)
    await db_session.commit()

    genuinely_missing_response = await other_api_client.delete(_cancel_url(invitation_id))

    assert not_your_org_response.status_code == genuinely_missing_response.status_code == 404
    # `request_id` is per-request and expected to differ; `code` and `message` are the
    # only fields a caller could use to tell the two cases apart, and they must match.
    not_your_org_body = not_your_org_response.json()
    genuinely_missing_body = genuinely_missing_response.json()
    assert not_your_org_body["code"] == genuinely_missing_body["code"] == "ResourceNotFoundError"
    assert not_your_org_body["message"] == genuinely_missing_body["message"]

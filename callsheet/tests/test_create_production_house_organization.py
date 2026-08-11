"""Tests for E01-S01 — Create a production house organization.

Story: stories/E01-organizations-access-membership/E01-S01-create-production-house-organization.md

The story has a single Gherkin scenario ("First-time production house user sets up
their studio workspace"), whose Given/When/Then clauses fan out into several backend
contracts:

  - a verified caller with no memberships can create an organization         (happy path)
  - the created organization records the caller as its OWNER via a membership row (ownership)
  - organization_type is persisted, not just echoed back                    (persistence)
  - an unverified caller is refused                                         (Given: verified email)
  - an unidentified caller is refused                                       (auth boundary)
  - a syntactically valid but unknown caller id is refused, like no caller  (auth boundary)
  - a duplicate slug is a conflict, with no partial org/membership left behind (conflict)
  - the (user_id, organization_id) uniqueness the membership table promises is real (schema)

"lands on an empty title list with a Create your first title CTA" is frontend routing
(see callsheet-ui/src/components/layout/workspace-gate.tsx and titles-page.tsx) and is
not exercised here — callsheet-ui has no test runner configured (no vitest/jest in
package.json), so that half of the Then clause is not covered by any automated test.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Membership, MembershipRole, Organization, User

ORGANIZATIONS_URL = "/api/v1/organizations"
ME_URL = "/api/v1/me"

SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}


# ---------------------------------------------------------------------------
# Scenario: First-time production house user sets up their studio workspace
# ---------------------------------------------------------------------------


async def test_first_time_user_creates_organization_and_is_recorded_as_owner(
    api_client: AsyncClient,
    pilot_user: User,
) -> None:
    """When: verified caller with no memberships submits studio name + Production House.

    Then: the organization is created with the caller recorded as its owner.
    """
    response = await api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Sun Pictures"
    assert body["slug"] == "sun-pictures"
    assert body["organization_type"] == "production_house"

    current_user = await api_client.get(ME_URL)
    memberships = current_user.json()["memberships"]
    assert len(memberships) == 1
    assert memberships[0]["role"] == "owner"
    assert memberships[0]["organization"]["id"] == body["id"]


async def test_owner_membership_row_has_owner_role_and_points_at_caller_and_organization(
    api_client: AsyncClient,
    pilot_user: User,
    db_session: AsyncSession,
) -> None:
    """Then: 'recorded as its owner' means a membership row, not a column on the org
    (see story Notes) — role=owner, user_id=caller, organization_id=the new org."""
    created = await api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)
    organization_id = uuid.UUID(created.json()["id"])

    result = await db_session.execute(
        select(Membership).where(Membership.organization_id == organization_id)
    )
    memberships = result.scalars().all()

    assert len(memberships) == 1
    membership = memberships[0]
    assert membership.role == MembershipRole.OWNER
    assert membership.user_id == pilot_user.id
    assert membership.organization_id == organization_id


async def test_created_organization_persists_organization_type(
    api_client: AsyncClient,
) -> None:
    """Notes: organization_type is stored on the record from day one. Round-trip
    through a fresh GET (not just the create response) to prove it was persisted."""
    created = await api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)
    organization_id = created.json()["id"]

    fetched = await api_client.get(f"{ORGANIZATIONS_URL}/{organization_id}")

    assert fetched.status_code == 200
    assert fetched.json()["organization_type"] == "production_house"


async def test_caller_with_no_memberships_has_empty_memberships_list(
    api_client: AsyncClient,
) -> None:
    """Given: I do not yet belong to any organization — this is the condition the
    frontend workspace-gate reads to route a caller to onboarding."""
    response = await api_client.get(ME_URL)

    assert response.status_code == 200
    assert response.json()["memberships"] == []


# ---------------------------------------------------------------------------
# Given: I have accepted a pilot invitation and verified my email
# ---------------------------------------------------------------------------


async def test_unverified_caller_cannot_create_organization(
    anonymous_api_client: AsyncClient,
    unverified_user: User,
    db_session: AsyncSession,
) -> None:
    """Given (negated): email not yet verified -> creation is refused, and nothing
    is left behind."""
    anonymous_api_client.headers["X-User-Id"] = str(unverified_user.id)

    response = await anonymous_api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)

    assert response.status_code == 403
    assert response.json()["code"] == "PermissionDeniedError"

    organizations = (await db_session.execute(select(Organization))).scalars().all()
    assert organizations == []


async def test_unverified_caller_can_still_view_their_own_profile(
    anonymous_api_client: AsyncClient,
    unverified_user: User,
) -> None:
    """The email-verification gate is scoped to organization creation, not to every
    authenticated route: an unverified caller can still see who they are."""
    anonymous_api_client.headers["X-User-Id"] = str(unverified_user.id)

    response = await anonymous_api_client.get(ME_URL)

    assert response.status_code == 200
    assert response.json()["memberships"] == []


# ---------------------------------------------------------------------------
# Auth boundary: the caller must be identifiable at all
# ---------------------------------------------------------------------------


async def test_unidentified_caller_cannot_create_organization(
    anonymous_api_client: AsyncClient,
) -> None:
    """A client that asserts no identity (no X-User-Id header) is refused."""
    response = await anonymous_api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_unknown_user_id_cannot_create_organization(
    anonymous_api_client: AsyncClient,
) -> None:
    """A syntactically valid X-User-Id that does not resolve to any user is refused."""
    anonymous_api_client.headers["X-User-Id"] = str(uuid.uuid4())

    response = await anonymous_api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_missing_and_unknown_caller_get_identical_responses(
    anonymous_api_client: AsyncClient,
) -> None:
    """user_service.resolve_caller() deliberately returns the same message for a
    missing header and an unknown id, so a caller probing for valid user ids learns
    nothing from the difference. Lock that behaviour in."""
    missing = await anonymous_api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)

    anonymous_api_client.headers["X-User-Id"] = str(uuid.uuid4())
    unknown = await anonymous_api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)

    assert missing.status_code == unknown.status_code == 401
    assert missing.json()["code"] == unknown.json()["code"]
    assert missing.json()["message"] == unknown.json()["message"]


async def test_unidentified_caller_cannot_read_current_user(
    anonymous_api_client: AsyncClient,
) -> None:
    response = await anonymous_api_client.get(ME_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_unknown_user_id_cannot_read_current_user(
    anonymous_api_client: AsyncClient,
) -> None:
    anonymous_api_client.headers["X-User-Id"] = str(uuid.uuid4())

    response = await anonymous_api_client.get(ME_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


# ---------------------------------------------------------------------------
# Given: "Production House" is an available organization type / slug conflicts
# ---------------------------------------------------------------------------


async def test_duplicate_slug_is_rejected_and_leaves_no_partial_state(
    api_client: AsyncClient,
    pilot_user: User,
    db_session: AsyncSession,
) -> None:
    """A second create with the same slug is a conflict. It must not create a second
    organization, and must not create a second membership for the caller."""
    first = await api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)
    assert first.status_code == 201

    second = await api_client.post(
        ORGANIZATIONS_URL,
        json={**SUN_PICTURES_PAYLOAD, "name": "Sun Pictures Two"},
    )

    assert second.status_code == 409
    assert second.json()["code"] == "ResourceConflictError"

    organizations = (
        (await db_session.execute(select(Organization).where(Organization.slug == "sun-pictures")))
        .scalars()
        .all()
    )
    assert len(organizations) == 1

    memberships = (
        (await db_session.execute(select(Membership).where(Membership.user_id == pilot_user.id)))
        .scalars()
        .all()
    )
    assert len(memberships) == 1


# ---------------------------------------------------------------------------
# Schema-level: the uniqueness the membership table promises
# ---------------------------------------------------------------------------


async def test_membership_table_rejects_duplicate_user_organization_pair(
    db_session: AsyncSession,
    pilot_user: User,
) -> None:
    """Notes: ownership is a membership row so it can be transferred later, but a
    given user still can't hold two membership rows for the same organization. The
    public API can't produce this state (slug conflicts stop a second create first),
    so exercise the constraint directly against the model."""
    organization = Organization(
        name="Sun Pictures",
        slug="sun-pictures",
        organization_type="production_house",
    )
    db_session.add(organization)
    await db_session.flush()

    db_session.add(
        Membership(
            user_id=pilot_user.id,
            organization_id=organization.id,
            role=MembershipRole.OWNER,
        )
    )
    await db_session.commit()

    db_session.add(
        Membership(
            user_id=pilot_user.id,
            organization_id=organization.id,
            role=MembershipRole.OWNER,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

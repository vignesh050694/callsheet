"""Tests for the two bugs a reviewer found in E01-S01's organization routes, and fixed.

Story: stories/E01-organizations-access-membership/E01-S01-create-production-house-organization.md

The story only describes the happy path ("First-time production house user sets up
their studio workspace") and the first-pass suite in
`test_create_production_house_organization.py` covers that scenario and its immediate
Given/When/Then boundary. It does not touch what happens to an organization *after*
creation, which is where the two bugs lived:

  FINDING 1 — every route except POST /organizations had no authentication at all.
  An anonymous client could list every organization across every tenant, and a
  verified-but-unrelated user could read, rename or delete a studio's organization
  just by guessing/enumerating its id. Fixed by (a) requiring `current_user` on all
  five routes, (b) scoping `get_organization` to callers who hold a membership
  (non-members get 404, identical to a genuinely missing id, so existence is not
  leaked), and (c) scoping `list_organizations` through membership joins instead of a
  bare table scan.

  FINDING 2 — slug uniqueness was check-then-insert: a race between the pre-check and
  the insert could surface as an unhandled IntegrityError -> 500 instead of a 409.
  Fixed by wrapping the commit in try/except IntegrityError -> ResourceConflictError.

This file covers the fixed behaviour. It does not re-litigate the happy path already
covered in test_create_production_house_organization.py, only the access-control
surface that story doesn't spell out in Gherkin but the story's Notes ("Owner is a
membership row") implies: only a member should ever see or touch an organization.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Organization, User

ORGANIZATIONS_URL = "/api/v1/organizations"

SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}

RAVI_FILMS_PAYLOAD = {
    "name": "Ravi Films",
    "slug": "ravi-films",
    "organization_type": "production_house",
}


async def _create_organization(client: AsyncClient, payload: dict) -> str:
    response = await client.post(ORGANIZATIONS_URL, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---------------------------------------------------------------------------
# FINDING 1a — every route requires an identified caller (401), not just POST
# ---------------------------------------------------------------------------


async def test_unidentified_caller_cannot_list_organizations(
    anonymous_api_client: AsyncClient,
) -> None:
    """Before the fix, GET /organizations had no `current_user` dependency at all:
    an anonymous client could list every organization across every tenant."""
    response = await anonymous_api_client.get(ORGANIZATIONS_URL)

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_unidentified_caller_cannot_read_an_organization(
    unauthenticated_client: AsyncClient,
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client, SUN_PICTURES_PAYLOAD)

    response = await unauthenticated_client.get(f"{ORGANIZATIONS_URL}/{organization_id}")

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_unidentified_caller_cannot_update_an_organization(
    unauthenticated_client: AsyncClient,
    api_client: AsyncClient,
) -> None:
    """Before the fix, PATCH had no `current_user` dependency: an anonymous client
    could rename any studio's organization."""
    organization_id = await _create_organization(api_client, SUN_PICTURES_PAYLOAD)

    response = await unauthenticated_client.patch(
        f"{ORGANIZATIONS_URL}/{organization_id}", json={"name": "Hijacked"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_unidentified_caller_cannot_delete_an_organization(
    unauthenticated_client: AsyncClient,
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Before the fix, DELETE had no `current_user` dependency: an anonymous client
    could delete any studio's organization. This is the regression test for the bug
    that mattered most."""
    organization_id = await _create_organization(api_client, SUN_PICTURES_PAYLOAD)

    response = await unauthenticated_client.delete(f"{ORGANIZATIONS_URL}/{organization_id}")

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"

    survivors = (
        (
            await db_session.execute(
                select(Organization).where(Organization.id == uuid.UUID(organization_id))
            )
        )
        .scalars()
        .all()
    )
    assert len(survivors) == 1


# ---------------------------------------------------------------------------
# FINDING 1b — a real, verified, non-member gets 404, not 403 (no existence leak)
# ---------------------------------------------------------------------------


async def test_non_member_cannot_read_another_users_organization(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client, SUN_PICTURES_PAYLOAD)

    response = await other_api_client.get(f"{ORGANIZATIONS_URL}/{organization_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_non_member_cannot_update_another_users_organization(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization_id = await _create_organization(api_client, SUN_PICTURES_PAYLOAD)

    response = await other_api_client.patch(
        f"{ORGANIZATIONS_URL}/{organization_id}", json={"name": "Hijacked"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"

    organization = await db_session.get(Organization, uuid.UUID(organization_id))
    assert organization is not None
    assert organization.name == "Sun Pictures"


async def test_non_member_cannot_delete_another_users_organization(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization_id = await _create_organization(api_client, SUN_PICTURES_PAYLOAD)

    response = await other_api_client.delete(f"{ORGANIZATIONS_URL}/{organization_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"

    organization = await db_session.get(Organization, uuid.UUID(organization_id))
    assert organization is not None


async def test_non_member_gets_same_404_as_a_genuinely_missing_organization(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
) -> None:
    """The service deliberately returns the identical not-found response for 'exists
    but you're not a member' and 'does not exist', so a caller probing ids learns
    nothing about which organizations exist. Lock the equivalence in, not just the
    status code."""
    organization_id = await _create_organization(api_client, SUN_PICTURES_PAYLOAD)

    real_but_foreign = await other_api_client.get(f"{ORGANIZATIONS_URL}/{organization_id}")
    genuinely_missing = await other_api_client.get(f"{ORGANIZATIONS_URL}/{uuid.uuid4()}")

    assert real_but_foreign.status_code == genuinely_missing.status_code == 404
    assert real_but_foreign.json()["code"] == genuinely_missing.json()["code"]


# ---------------------------------------------------------------------------
# FINDING 1c — list is scoped to the caller's own memberships
# ---------------------------------------------------------------------------


async def test_list_organizations_is_scoped_to_the_callers_memberships(
    api_client: AsyncClient,
    other_api_client: AsyncClient,
) -> None:
    """Two users, each owning their own organization: each caller's list contains
    only their own, and `total` reflects that scoping too (not a global count)."""
    sun_pictures_id = await _create_organization(api_client, SUN_PICTURES_PAYLOAD)
    ravi_films_id = await _create_organization(other_api_client, RAVI_FILMS_PAYLOAD)

    pilot_view = (await api_client.get(ORGANIZATIONS_URL)).json()
    other_view = (await other_api_client.get(ORGANIZATIONS_URL)).json()

    assert [item["id"] for item in pilot_view["items"]] == [sun_pictures_id]
    assert pilot_view["total"] == 1

    assert [item["id"] for item in other_view["items"]] == [ravi_films_id]
    assert other_view["total"] == 1


# ---------------------------------------------------------------------------
# The legitimate path must still work: a member can read/update/delete their own org
# ---------------------------------------------------------------------------


async def test_member_can_still_read_their_own_organization(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client, SUN_PICTURES_PAYLOAD)

    response = await api_client.get(f"{ORGANIZATIONS_URL}/{organization_id}")

    assert response.status_code == 200
    assert response.json()["id"] == organization_id


async def test_member_can_still_update_their_own_organization(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client, SUN_PICTURES_PAYLOAD)

    response = await api_client.patch(
        f"{ORGANIZATIONS_URL}/{organization_id}", json={"name": "Sun Pictures Studios"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Sun Pictures Studios"


async def test_member_can_still_delete_their_own_organization(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization_id = await _create_organization(api_client, SUN_PICTURES_PAYLOAD)

    response = await api_client.delete(f"{ORGANIZATIONS_URL}/{organization_id}")

    assert response.status_code == 204

    organization = await db_session.get(Organization, uuid.UUID(organization_id))
    assert organization is None


# ---------------------------------------------------------------------------
# FINDING 2 — IntegrityError at commit time is translated to 409, not 500
# ---------------------------------------------------------------------------


async def test_create_organization_returns_conflict_when_commit_time_insert_collides(
    api_client: AsyncClient,
    pilot_user: User,
    db_session: AsyncSession,
) -> None:
    """A slug collision that slips past the pre-check returns 409, not a 500.

    This is a forced approximation of the race, not a real concurrency test: the
    fixtures share one `AsyncSession` for the whole test and httpx's ASGI transport
    runs requests sequentially, so two genuinely concurrent HTTP requests cannot be
    produced here. Instead it reproduces the same *shape*: a colliding `Organization`
    row is added to the session but kept un-flushed (autoflush disabled) so
    `_ensure_slug_is_available`'s SELECT-based pre-check does not see it and reports
    the slug as available — exactly what a real second writer racing the pre-check
    would also see.

    Why the guard has to cover more than the commit: `OrganizationRepository.add()`
    calls `session.flush()` immediately after `session.add()`, and the flush is what
    issues the INSERT. A plain, non-deferrable UNIQUE index — SQLite or Postgres — is
    checked at INSERT time rather than deferred to COMMIT, so the `IntegrityError`
    surfaces from `add()`, not from the later `commit()`. An earlier version of the
    fix wrapped only `commit()` and therefore never fired; `create_organization` now
    wraps the whole write region, which is what this test pins down.
    """
    with db_session.no_autoflush:
        colliding_organization = Organization(
            name="Existing Sun Pictures",
            slug="sun-pictures",
            organization_type="production_house",
        )
        db_session.add(colliding_organization)

        response = await api_client.post(ORGANIZATIONS_URL, json=SUN_PICTURES_PAYLOAD)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ResourceConflictError"

    # The whole transaction (the manually-added colliding row *and* the service's
    # attempted insert) rolls back together: nothing with this slug survives, and no
    # membership was left dangling for the caller.
    organizations = (
        (await db_session.execute(select(Organization).where(Organization.slug == "sun-pictures")))
        .scalars()
        .all()
    )
    assert organizations == []

"""Business logic for organizations (E01-S01).

Owns the transaction boundary and every rule. Knows nothing about status codes —
it raises domain errors and lets the API layer translate them.
"""

import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PermissionDeniedError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from app.repositories.membership_repository import MembershipRepository
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.organization import OrganizationCreate, OrganizationUpdate

_logger = structlog.get_logger(__name__)

UNVERIFIED_EMAIL_MESSAGE = "Verify your email address before creating an organization"
SLUG_TAKEN_MESSAGE = "An organization with slug {slug!r} already exists"
ORGANIZATION_NOT_FOUND_MESSAGE = "Organization {id} was not found"
NOT_AN_OWNER_MESSAGE = "Only an owner can change this organization"


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._organization_repository = OrganizationRepository(session)
        self._membership_repository = MembershipRepository(session)

    async def create_organization(self, payload: OrganizationCreate, owner: User) -> Organization:
        """Creates the organization and the creator's owner membership as one unit.

        Both rows land in a single transaction: an organization with no owner would be
        unreachable, since every route into it goes through a membership.
        """
        self._ensure_email_is_verified(owner)
        await self._ensure_slug_is_available(payload.slug)

        organization = Organization(
            name=payload.name,
            slug=payload.slug,
            organization_type=payload.organization_type,
        )
        try:
            # The whole write is guarded, not just the commit: `add` flushes, and a flush
            # is what issues the INSERT, so a unique-slug collision surfaces here rather
            # than at commit time.
            await self._organization_repository.add(organization)
            await self._membership_repository.add(
                Membership(
                    user_id=owner.id,
                    organization_id=organization.id,
                    role=MembershipRole.OWNER,
                )
            )
            await self._session.commit()
        except IntegrityError:
            # The pre-check above narrows the window but cannot close it: two concurrent
            # requests can both pass it and race to insert. The unique index is the real
            # arbiter, so a loser is translated to the same conflict, not a 500.
            await self._session.rollback()
            _logger.warning("organization.create.slug_conflict_on_insert", slug=payload.slug)
            raise ResourceConflictError(SLUG_TAKEN_MESSAGE.format(slug=payload.slug)) from None

        await self._session.refresh(organization)

        _logger.info(
            "organization.created",
            organization_id=str(organization.id),
            slug=organization.slug,
            owner_user_id=str(owner.id),
        )
        return organization

    async def get_organization(self, organization_id: uuid.UUID, caller: User) -> Organization:
        """Membership is what makes an organization visible.

        A non-member gets the same "not found" a genuinely missing id gets — telling them
        the organization exists but is not theirs would leak the tenant list.
        """
        organization = await self._organization_repository.get_by_id(organization_id)
        if organization is None:
            raise ResourceNotFoundError(ORGANIZATION_NOT_FOUND_MESSAGE.format(id=organization_id))

        membership = await self._membership_repository.get_for_user_and_organization(
            caller.id, organization_id
        )
        if membership is None:
            _logger.warning(
                "organization.access.not_a_member",
                organization_id=str(organization_id),
                user_id=str(caller.id),
            )
            raise ResourceNotFoundError(ORGANIZATION_NOT_FOUND_MESSAGE.format(id=organization_id))

        return organization

    async def list_organizations(
        self, caller: User, *, limit: int, offset: int
    ) -> tuple[list[Organization], int]:
        """Scoped to the caller's memberships — never a cross-tenant listing."""
        organizations = await self._organization_repository.list_for_user(
            caller.id, limit=limit, offset=offset
        )
        total_count = await self._organization_repository.count_for_user(caller.id)
        return organizations, total_count

    async def update_organization(
        self, organization_id: uuid.UUID, payload: OrganizationUpdate, caller: User
    ) -> Organization:
        organization = await self.get_organization(organization_id, caller)
        await self._ensure_caller_can_administer(organization_id, caller)

        updated_fields = payload.model_dump(exclude_unset=True)
        for field_name, field_value in updated_fields.items():
            setattr(organization, field_name, field_value)

        await self._session.commit()
        await self._session.refresh(organization)

        _logger.info(
            "organization.updated",
            organization_id=str(organization.id),
            updated_fields=sorted(updated_fields),
        )
        return organization

    async def delete_organization(self, organization_id: uuid.UUID, caller: User) -> None:
        organization = await self.get_organization(organization_id, caller)
        await self._ensure_caller_can_administer(organization_id, caller)
        await self._organization_repository.delete(organization)
        await self._session.commit()
        _logger.info(
            "organization.deleted",
            organization_id=str(organization_id),
            user_id=str(caller.id),
        )

    async def _ensure_caller_can_administer(self, organization_id: uuid.UUID, caller: User) -> None:
        """A viewer reads; only an owner changes. Enforced here, not by hiding UI controls.

        The caller has already passed the membership check, so a refusal here is a genuine
        403: they can see this organization, they just may not administer it.
        """
        membership = await self._membership_repository.get_for_user_and_organization(
            caller.id, organization_id
        )
        if membership is None or not membership.role.can_administer_organization:
            _logger.warning(
                "organization.permission_denied",
                organization_id=str(organization_id),
                user_id=str(caller.id),
            )
            raise PermissionDeniedError(NOT_AN_OWNER_MESSAGE)

    @staticmethod
    def _ensure_email_is_verified(owner: User) -> None:
        """Pilot access is granted by invitation, and the invitation is only complete
        once the address it was sent to has been verified."""
        if not owner.is_email_verified:
            _logger.warning("organization.create.unverified_email", user_id=str(owner.id))
            raise PermissionDeniedError(UNVERIFIED_EMAIL_MESSAGE)

    async def _ensure_slug_is_available(self, slug: str) -> None:
        """Slugs are the public URL key, so a collision is a conflict, not a validation error."""
        existing_organization = await self._organization_repository.get_by_slug(slug)
        if existing_organization is not None:
            _logger.warning("organization.create.slug_conflict", slug=slug)
            raise ResourceConflictError(SLUG_TAKEN_MESSAGE.format(slug=slug))

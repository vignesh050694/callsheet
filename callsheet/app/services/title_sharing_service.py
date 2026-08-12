"""Sharing a title with an agency organization (E01-S05).

Separate from `TitleMembershipService` for the same reason that one is separate from
`TitleInvitationService`: these are different grants with different shapes. Tagging an
artist creates a pending offer addressed to a person who may not have an account. Sharing
with an agency creates live access held by an organization that is already here — nothing
is sent, nothing is accepted, and the access starts immediately.

Access follows the organization rather than the individual because agency staff change
mid-engagement. Granting to a named person means the studio has to re-invite every new
account by hand, and the failure mode of forgetting is that a departed employee keeps
watching the film.
"""

import uuid

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from app.models.access_audit import AccessAuditAction, AccessAuditEvent
from app.models.organization import Organization, OrganizationType
from app.models.title_membership import (
    TitleMembership,
    TitleMembershipStatus,
    TitleRole,
)
from app.models.user import User
from app.repositories.access_audit_repository import AccessAuditRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.title_membership_repository import TitleMembershipRepository
from app.services.title_access import TitleAccessPolicy

_logger = structlog.get_logger(__name__)

ORGANIZATION_NOT_FOUND_MESSAGE = "Organization {id} was not found"
NOT_AN_AGENCY_MESSAGE = (
    "'{name}' is not an agency. A title can only be shared with an agency organization"
)
SELF_SHARE_MESSAGE = "This title already belongs to that organization"
ALREADY_SHARED_MESSAGE = "'{name}' already has access to this title"


class TitleSharingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._membership_repository = TitleMembershipRepository(session)
        self._organization_repository = OrganizationRepository(session)
        self._audit_repository = AccessAuditRepository(session)
        self._access_policy = TitleAccessPolicy(session)

    async def share_with_agency(
        self, title_id: uuid.UUID, agency_organization_id: uuid.UUID, caller: User
    ) -> TitleMembership:
        """Grants one agency organization access to exactly this title."""
        access = await self._access_policy.require_administrable(title_id, caller)
        title = access.title
        agency = await self._require_agency(agency_organization_id)
        if agency.id == title.organization_id:
            raise ValidationFailedError(SELF_SHARE_MESSAGE)

        membership = TitleMembership(
            title_id=title_id,
            subject_organization_id=agency.id,
            role=TitleRole.AGENCY_MANAGER,
            # Live immediately. There is no invitation to accept: the organization is
            # already on the platform, and the studio's action is the whole grant.
            status=TitleMembershipStatus.ACTIVE,
            invited_by_user_id=caller.id,
        )
        # Written in the same transaction as the grant, so access cannot exist without
        # the record of who gave it — and a failed grant leaves no audit row claiming
        # otherwise.
        await self._record_grant(title_id, agency, caller)

        agency_name = agency.name
        try:
            await self._membership_repository.add(membership)
            await self._session.commit()
        except IntegrityError:
            # Nothing below may read an ORM object — `rollback()` expires them all, which
            # is why the name was taken into a local first.
            await self._session.rollback()
            _logger.warning(
                "title_sharing.conflict",
                title_id=str(title_id),
                agency_organization_id=str(agency_organization_id),
            )
            raise ResourceConflictError(ALREADY_SHARED_MESSAGE.format(name=agency_name)) from None

        _logger.info(
            "title_sharing.granted",
            membership_id=str(membership.id),
            title_id=str(title_id),
            agency_organization_id=str(agency_organization_id),
            granted_by_user_id=str(caller.id),
        )
        return await self._reload(membership.id)

    async def list_audit_events(self, title_id: uuid.UUID, caller: User) -> list[AccessAuditEvent]:
        """Who has been let in and out of this title. The owning organization only.

        A shared grant gets the same 404 the member list gives it, rather than a 403. The
        two are the same kind of surface — both describe other people's relationship to
        the title — so they have to refuse the same way. A 403 here would also be the
        wrong sentence entirely: it speaks to editing rights, and this is a read.
        """
        await self._access_policy.require_owning_organization(title_id, caller)
        return await self._audit_repository.list_for_title(title_id)

    async def _record_grant(self, title_id: uuid.UUID, agency: Organization, caller: User) -> None:
        await self._audit_repository.add(
            AccessAuditEvent(
                title_id=title_id,
                action=AccessAuditAction.GRANTED,
                role=TitleRole.AGENCY_MANAGER,
                actor_user_id=caller.id,
                subject_organization_id=agency.id,
                # Denormalised so the row still reads if the agency is deleted later.
                subject_name=agency.name,
            )
        )

    async def _require_agency(self, organization_id: uuid.UUID) -> Organization:
        """The grantee has to be an agency, and it has to exist.

        Checked rather than assumed because the role granted is "agency manager" — issuing
        it to a production house would give another studio a role whose scope was never
        designed for them.
        """
        organization = await self._organization_repository.get_by_id(organization_id)
        if organization is None:
            raise ResourceNotFoundError(ORGANIZATION_NOT_FOUND_MESSAGE.format(id=organization_id))
        if organization.organization_type is not OrganizationType.AGENCY:
            raise ValidationFailedError(NOT_AN_AGENCY_MESSAGE.format(name=organization.name))
        return organization

    async def _reload(self, membership_id: uuid.UUID) -> TitleMembership:
        """Re-reads with relationships loaded — `lazy="raise"` refuses a lazy load."""
        membership = await self._membership_repository.get_by_id(membership_id)
        if membership is None:
            raise ResourceNotFoundError(f"Membership {membership_id} was not found")
        return membership

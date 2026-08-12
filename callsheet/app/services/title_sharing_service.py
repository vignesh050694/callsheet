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
from datetime import UTC, datetime

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
MEMBERSHIP_NOT_FOUND_MESSAGE = "Membership {id} was not found"
ALREADY_REVOKED_MESSAGE = "This access has already been revoked"
UNKNOWN_SUBJECT_NAME = "Unknown subject"


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

        existing = await self._membership_repository.get_for_title_and_organization(
            title_id, agency.id
        )
        if existing is not None:
            # A revoked grant still occupies `uq_title_membership_organization`, so a
            # client returning for a second engagement would otherwise be refused as a
            # duplicate. Reactivating the row keeps both of its audit entries pointing at
            # one history rather than splitting it across two rows.
            return await self._reactivate(existing, agency, caller)

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

    async def revoke_access(
        self, title_id: uuid.UUID, membership_id: uuid.UUID, caller: User
    ) -> TitleMembership:
        """Ends a grant, with effect on the partner's very next request (E01-S06).

        Nothing has to be pushed or invalidated for that to be true: every query that
        resolves access filters on `ACTIVE`, so flipping the status is the whole
        enforcement. An agency with the dashboard open keeps whatever is already painted
        on their screen — this cannot reach into a browser — and fails on the next call
        they make, which is what "immediate" can honestly mean here.

        The row is tombstoned rather than deleted, unlike untagging. An engagement that
        ended is exactly the thing someone reconstructs later, and a deleted row takes its
        history with it. `share_with_agency` reactivates this row if the client comes back.
        """
        await self._access_policy.require_administrable(title_id, caller)
        membership = await self._require_membership_on_title(title_id, membership_id)
        if membership.status is TitleMembershipStatus.REVOKED:
            raise ValidationFailedError(ALREADY_REVOKED_MESSAGE)

        subject_name = self._subject_name_of(membership)
        membership.status = TitleMembershipStatus.REVOKED
        membership.revoked_at = datetime.now(UTC)
        # A pending invitation must not stay redeemable after it is revoked — otherwise
        # the link already in someone's inbox still lets them in.
        membership.token_hash = None

        await self._audit_repository.add(
            AccessAuditEvent(
                title_id=title_id,
                action=AccessAuditAction.REVOKED,
                role=membership.role,
                actor_user_id=caller.id,
                subject_organization_id=membership.subject_organization_id,
                subject_user_id=membership.subject_user_id,
                subject_name=subject_name,
            )
        )
        await self._session.commit()

        _logger.info(
            "title_sharing.revoked",
            membership_id=str(membership_id),
            title_id=str(title_id),
            role=str(membership.role),
            revoked_by_user_id=str(caller.id),
        )
        return await self._reload(membership_id)

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

    async def _reactivate(
        self, membership: TitleMembership, agency: Organization, caller: User
    ) -> TitleMembership:
        """Re-grants a previously revoked share. A live one is a conflict, not a no-op."""
        if membership.status is not TitleMembershipStatus.REVOKED:
            raise ResourceConflictError(ALREADY_SHARED_MESSAGE.format(name=agency.name))

        membership.status = TitleMembershipStatus.ACTIVE
        membership.revoked_at = None
        membership.invited_by_user_id = caller.id
        await self._record_grant(membership.title_id, agency, caller)
        await self._session.commit()

        _logger.info(
            "title_sharing.regranted",
            membership_id=str(membership.id),
            title_id=str(membership.title_id),
            agency_organization_id=str(agency.id),
            granted_by_user_id=str(caller.id),
        )
        return await self._reload(membership.id)

    async def _require_membership_on_title(
        self, title_id: uuid.UUID, membership_id: uuid.UUID
    ) -> TitleMembership:
        """A membership id from another title is a 404, not someone else's grant to end."""
        membership = await self._membership_repository.get_by_id(membership_id)
        if membership is None or membership.title_id != title_id:
            raise ResourceNotFoundError(MEMBERSHIP_NOT_FOUND_MESSAGE.format(id=membership_id))
        return membership

    @staticmethod
    def _subject_name_of(membership: TitleMembership) -> str:
        """Read before the write, and denormalised into the audit row.

        A membership names an organization or a person, never both, and the audit log has
        to still read after either is deleted.
        """
        if membership.subject_organization is not None:
            return membership.subject_organization.name
        if membership.artist is not None:
            return membership.artist.display_name
        return UNKNOWN_SUBJECT_NAME

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

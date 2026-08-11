"""Business logic for invitations and organization membership (E01-S02).

Owns the transaction boundary and every rule about who may invite whom. Knows nothing
about status codes — it raises domain errors and lets the API layer translate them.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PermissionDeniedError,
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from app.core.tokens import generate_invitation_token, hash_invitation_token
from app.models.invitation import Invitation, InvitationStatus
from app.models.membership import Membership
from app.models.organization import Organization
from app.models.user import User
from app.repositories.invitation_repository import InvitationRepository
from app.repositories.membership_repository import MembershipRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.invitation import InvitationCreate
from app.services.invitation_notifier import InvitationNotifier

_logger = structlog.get_logger(__name__)

NOT_AN_OWNER_MESSAGE = "Only an owner can manage members of this organization"
ORGANIZATION_NOT_FOUND_MESSAGE = "Organization {id} was not found"
INVITATION_NOT_FOUND_MESSAGE = "Invitation {id} was not found"
ALREADY_A_MEMBER_MESSAGE = "{email} is already a member of this organization"
ALREADY_INVITED_MESSAGE = "{email} already has a pending invitation"
INVALID_TOKEN_MESSAGE = "This invitation link is not valid"
WRONG_RECIPIENT_MESSAGE = "This invitation was sent to a different email address"
SELF_INVITE_MESSAGE = "You are already a member of this organization"
UNVERIFIED_EMAIL_MESSAGE = "Verify your email address before accepting an invitation"


class InvitationService:
    def __init__(self, session: AsyncSession, notifier: InvitationNotifier) -> None:
        self._session = session
        self._notifier = notifier
        self._invitation_repository = InvitationRepository(session)
        self._membership_repository = MembershipRepository(session)
        self._organization_repository = OrganizationRepository(session)
        self._user_repository = UserRepository(session)

    async def invite_member(
        self, organization_id: uuid.UUID, payload: InvitationCreate, inviter: User
    ) -> tuple[Invitation, str]:
        """Mints a pending invitation and hands back the raw token exactly once."""
        organization = await self._require_owner(organization_id, inviter)
        await self._ensure_email_is_invitable(organization_id, payload.email)

        raw_token = generate_invitation_token()
        invitation = Invitation(
            organization_id=organization_id,
            email=payload.email,
            role=payload.role,
            status=InvitationStatus.PENDING,
            token_hash=hash_invitation_token(raw_token),
            invited_by_user_id=inviter.id,
            last_sent_at=datetime.now(UTC),
        )
        try:
            await self._invitation_repository.add(invitation)
            await self._session.commit()
        except IntegrityError:
            # A token-hash collision is astronomically unlikely, but a raced insert is
            # not worth a 500 either way.
            await self._session.rollback()
            _logger.warning("invitation.create.conflict", organization_id=str(organization_id))
            raise ResourceConflictError(
                ALREADY_INVITED_MESSAGE.format(email=payload.email)
            ) from None

        await self._session.refresh(invitation)

        await self._notifier.send_invitation(invitation, organization.name)
        _logger.info(
            "invitation.created",
            invitation_id=str(invitation.id),
            organization_id=str(organization_id),
            role=str(payload.role),
            invited_by_user_id=str(inviter.id),
        )
        return invitation, raw_token

    async def resend_invitation(
        self, invitation_id: uuid.UUID, caller: User
    ) -> tuple[Invitation, str]:
        """Re-issues the token, so a resent link supersedes the one that went astray."""
        invitation = await self._require_pending_invitation(invitation_id, caller)
        organization = await self._require_owner(invitation.organization_id, caller)

        raw_token = generate_invitation_token()
        invitation.token_hash = hash_invitation_token(raw_token)
        invitation.last_sent_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(invitation)

        await self._notifier.send_invitation(invitation, organization.name)
        _logger.info("invitation.resent", invitation_id=str(invitation.id))
        return invitation, raw_token

    async def cancel_invitation(self, invitation_id: uuid.UUID, caller: User) -> None:
        invitation = await self._require_pending_invitation(invitation_id, caller)
        await self._require_owner(invitation.organization_id, caller)

        invitation.status = InvitationStatus.CANCELLED
        await self._session.commit()
        _logger.info("invitation.cancelled", invitation_id=str(invitation.id))

    async def accept_invitation(self, raw_token: str, accepter: User) -> Membership:
        """Turns a held token into a membership, for the person it was addressed to."""
        invitation = await self._invitation_repository.get_pending_by_token_hash(
            hash_invitation_token(raw_token)
        )
        if invitation is None:
            _logger.warning("invitation.accept.invalid_token", user_id=str(accepter.id))
            raise ResourceNotFoundError(INVALID_TOKEN_MESSAGE)

        self._ensure_email_is_verified(accepter)

        if invitation.email != accepter.email.strip().lower():
            # The token alone is not enough: it has to be redeemed by its addressee, or
            # a forwarded link would let anyone into the organization.
            _logger.warning(
                "invitation.accept.wrong_recipient",
                invitation_id=str(invitation.id),
                user_id=str(accepter.id),
            )
            raise PermissionDeniedError(WRONG_RECIPIENT_MESSAGE)

        existing_membership = await self._membership_repository.get_for_user_and_organization(
            accepter.id, invitation.organization_id
        )
        if existing_membership is not None:
            raise ResourceConflictError(SELF_INVITE_MESSAGE)

        membership = Membership(
            user_id=accepter.id,
            organization_id=invitation.organization_id,
            role=invitation.role,
        )
        # Read off the identifiers before the write. `rollback()` expires every ORM
        # object in the session, and reading an expired attribute afterwards would
        # trigger a lazy reload that AsyncSession cannot service — so the failure path
        # must not touch `invitation` at all.
        invitation_id = str(invitation.id)
        accepter_id = str(accepter.id)
        invited_role = invitation.role

        try:
            # The check above narrows the window but cannot close it: a double-submit or
            # two racing accepts can both pass it. The (user_id, organization_id) unique
            # constraint is the real arbiter, so a loser becomes a conflict, not a 500.
            await self._membership_repository.add(membership)
            invitation.status = InvitationStatus.ACCEPTED
            invitation.accepted_at = datetime.now(UTC)
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            _logger.warning(
                "invitation.accept.membership_conflict",
                invitation_id=invitation_id,
                user_id=accepter_id,
            )
            raise ResourceConflictError(SELF_INVITE_MESSAGE) from None

        await self._session.refresh(membership)

        _logger.info(
            "invitation.accepted",
            invitation_id=invitation_id,
            user_id=accepter_id,
            role=str(invited_role),
        )
        return membership

    async def list_members(
        self, organization_id: uuid.UUID, caller: User
    ) -> tuple[list[Membership], list[Invitation]]:
        """Any member may see who else is in; only owners may change it."""
        await self._require_membership(organization_id, caller)
        members = await self._membership_repository.list_for_organization(organization_id)
        pending = await self._invitation_repository.list_pending_for_organization(organization_id)
        return members, pending

    async def _require_membership(self, organization_id: uuid.UUID, caller: User) -> Membership:
        membership = await self._membership_repository.get_for_user_and_organization(
            caller.id, organization_id
        )
        if membership is None:
            # Same "not found" a missing organization gets — a non-member learns nothing.
            raise ResourceNotFoundError(ORGANIZATION_NOT_FOUND_MESSAGE.format(id=organization_id))
        return membership

    async def _require_owner(self, organization_id: uuid.UUID, caller: User) -> Organization:
        """Owner-only actions return 403 to a viewer, who legitimately sees the org exists."""
        membership = await self._require_membership(organization_id, caller)
        if not membership.role.can_administer_organization:
            _logger.warning(
                "invitation.permission_denied",
                organization_id=str(organization_id),
                user_id=str(caller.id),
                role=str(membership.role),
            )
            raise PermissionDeniedError(NOT_AN_OWNER_MESSAGE)

        organization = await self._organization_repository.get_by_id(organization_id)
        if organization is None:
            raise ResourceNotFoundError(ORGANIZATION_NOT_FOUND_MESSAGE.format(id=organization_id))
        return organization

    async def _require_pending_invitation(
        self, invitation_id: uuid.UUID, caller: User
    ) -> Invitation:
        invitation = await self._invitation_repository.get_by_id(invitation_id)
        if invitation is None:
            raise ResourceNotFoundError(INVITATION_NOT_FOUND_MESSAGE.format(id=invitation_id))

        # Membership is checked before status, so a non-member cannot tell an accepted
        # invitation from one that never existed. The message is the invitation's, not
        # the organization's, so a caller holding a guessed id cannot tell "no such
        # invitation" from "not yours" either.
        try:
            await self._require_membership(invitation.organization_id, caller)
        except ResourceNotFoundError:
            raise ResourceNotFoundError(
                INVITATION_NOT_FOUND_MESSAGE.format(id=invitation_id)
            ) from None

        if not invitation.is_pending:
            raise ValidationFailedError(
                f"Invitation {invitation_id} is {invitation.status}, not pending"
            )
        return invitation

    @staticmethod
    def _ensure_email_is_verified(accepter: User) -> None:
        """Same bar organization creation sets: an unverified address is not yet a person."""
        if not accepter.is_email_verified:
            _logger.warning("invitation.accept.unverified_email", user_id=str(accepter.id))
            raise PermissionDeniedError(UNVERIFIED_EMAIL_MESSAGE)

    async def _ensure_email_is_invitable(self, organization_id: uuid.UUID, email: str) -> None:
        existing_user = await self._user_repository.get_by_email(email)
        if existing_user is not None:
            membership = await self._membership_repository.get_for_user_and_organization(
                existing_user.id, organization_id
            )
            if membership is not None:
                raise ResourceConflictError(ALREADY_A_MEMBER_MESSAGE.format(email=email))

        pending = await self._invitation_repository.get_pending_for_email(organization_id, email)
        if pending is not None:
            raise ResourceConflictError(ALREADY_INVITED_MESSAGE.format(email=email))

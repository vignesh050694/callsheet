"""Data access for invitations. Queries only — no business rules, no HTTP."""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invitation import Invitation, InvitationStatus

_logger = structlog.get_logger(__name__)


class InvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, invitation_id: uuid.UUID) -> Invitation | None:
        _logger.debug("invitation.query.get_by_id", invitation_id=str(invitation_id))
        return await self._session.get(Invitation, invitation_id)

    async def get_pending_by_token_hash(self, token_hash: str) -> Invitation | None:
        """Eager-loads the organization: accepting needs it, and the relationship raises on lazy."""
        _logger.debug("invitation.query.get_pending_by_token_hash")
        result = await self._session.execute(
            select(Invitation)
            .options(selectinload(Invitation.organization))
            .where(
                Invitation.token_hash == token_hash,
                Invitation.status == InvitationStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_for_email(
        self, organization_id: uuid.UUID, email: str
    ) -> Invitation | None:
        result = await self._session.execute(
            select(Invitation).where(
                Invitation.organization_id == organization_id,
                Invitation.email == email,
                Invitation.status == InvitationStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()

    async def list_pending_for_organization(self, organization_id: uuid.UUID) -> list[Invitation]:
        _logger.debug(
            "invitation.query.list_pending_for_organization",
            organization_id=str(organization_id),
        )
        result = await self._session.execute(
            select(Invitation)
            .where(
                Invitation.organization_id == organization_id,
                Invitation.status == InvitationStatus.PENDING,
            )
            .order_by(Invitation.created_at.asc())
        )
        return list(result.scalars().all())

    async def add(self, invitation: Invitation) -> Invitation:
        self._session.add(invitation)
        await self._session.flush()
        return invitation

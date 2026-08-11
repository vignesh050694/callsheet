"""Data access for memberships. Queries only — no business rules, no HTTP."""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.membership import Membership

_logger = structlog.get_logger(__name__)


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: uuid.UUID) -> list[Membership]:
        """Eager-loads the organization: callers render the two together, never the role alone."""
        _logger.debug("membership.query.list_for_user", user_id=str(user_id))
        result = await self._session.execute(
            select(Membership)
            .options(selectinload(Membership.organization))
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[Membership]:
        """Eager-loads the user: the Members screen renders the person, not the row."""
        _logger.debug(
            "membership.query.list_for_organization", organization_id=str(organization_id)
        )
        result = await self._session.execute(
            select(Membership)
            .options(selectinload(Membership.user))
            .where(Membership.organization_id == organization_id)
            .order_by(Membership.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_for_user_and_organization(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> Membership | None:
        _logger.debug(
            "membership.query.get_for_user_and_organization",
            user_id=str(user_id),
            organization_id=str(organization_id),
        )
        result = await self._session.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def add(self, membership: Membership) -> Membership:
        self._session.add(membership)
        await self._session.flush()
        return membership

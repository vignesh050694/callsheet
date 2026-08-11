"""Data access for organizations.

Queries only. No business rules, no HTTP. Every method returns ORM objects or plain
values and leaves the commit to the service that owns the transaction.
"""

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.membership import Membership
from app.models.organization import Organization

_logger = structlog.get_logger(__name__)


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, organization_id: uuid.UUID) -> Organization | None:
        _logger.debug("organization.query.get_by_id", organization_id=str(organization_id))
        return await self._session.get(Organization, organization_id)

    async def get_by_slug(self, slug: str) -> Organization | None:
        _logger.debug("organization.query.get_by_slug", slug=slug)
        result = await self._session.execute(select(Organization).where(Organization.slug == slug))
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[Organization]:
        """Joined through memberships: a caller never sees an organization they do not belong to."""
        _logger.debug("organization.query.list_for_user", user_id=str(user_id))
        result = await self._session.execute(
            select(Organization)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user_id)
            .order_by(Organization.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_for_user(self, user_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Organization)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user_id)
        )
        return int(result.scalar_one())

    async def add(self, organization: Organization) -> Organization:
        self._session.add(organization)
        await self._session.flush()
        return organization

    async def delete(self, organization: Organization) -> None:
        await self._session.delete(organization)
        await self._session.flush()

"""Data access for organizations.

Queries only. No business rules, no HTTP. Every method returns ORM objects or plain
values and leaves the commit to the service that owns the transaction.
"""

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def list_paginated(self, *, limit: int, offset: int) -> list[Organization]:
        _logger.debug("organization.query.list", limit=limit, offset=offset)
        result = await self._session.execute(
            select(Organization)
            .order_by(Organization.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_all(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(Organization))
        return int(result.scalar_one())

    async def add(self, organization: Organization) -> Organization:
        self._session.add(organization)
        await self._session.flush()
        return organization

    async def delete(self, organization: Organization) -> None:
        await self._session.delete(organization)
        await self._session.flush()

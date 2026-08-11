"""Business logic for organizations (E01-S01).

Owns the transaction boundary and every rule. Knows nothing about status codes —
it raises domain errors and lets the API layer translate them.
"""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceConflictError, ResourceNotFoundError
from app.models.organization import Organization
from app.repositories.organization_repository import OrganizationRepository
from app.schemas.organization import OrganizationCreate, OrganizationUpdate

_logger = structlog.get_logger(__name__)


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._organization_repository = OrganizationRepository(session)

    async def create_organization(self, payload: OrganizationCreate) -> Organization:
        await self._ensure_slug_is_available(payload.slug)

        organization = Organization(
            name=payload.name,
            slug=payload.slug,
            organization_type=payload.organization_type,
        )
        await self._organization_repository.add(organization)
        await self._session.commit()
        await self._session.refresh(organization)

        _logger.info(
            "organization.created",
            organization_id=str(organization.id),
            slug=organization.slug,
        )
        return organization

    async def get_organization(self, organization_id: uuid.UUID) -> Organization:
        organization = await self._organization_repository.get_by_id(organization_id)
        if organization is None:
            raise ResourceNotFoundError(f"Organization {organization_id} was not found")
        return organization

    async def list_organizations(
        self, *, limit: int, offset: int
    ) -> tuple[list[Organization], int]:
        organizations = await self._organization_repository.list_paginated(
            limit=limit, offset=offset
        )
        total_count = await self._organization_repository.count_all()
        return organizations, total_count

    async def update_organization(
        self, organization_id: uuid.UUID, payload: OrganizationUpdate
    ) -> Organization:
        organization = await self.get_organization(organization_id)

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

    async def delete_organization(self, organization_id: uuid.UUID) -> None:
        organization = await self.get_organization(organization_id)
        await self._organization_repository.delete(organization)
        await self._session.commit()
        _logger.info("organization.deleted", organization_id=str(organization_id))

    async def _ensure_slug_is_available(self, slug: str) -> None:
        """Slugs are the public URL key, so a collision is a conflict, not a validation error."""
        existing_organization = await self._organization_repository.get_by_slug(slug)
        if existing_organization is not None:
            _logger.warning("organization.create.slug_conflict", slug=slug)
            raise ResourceConflictError(f"An organization with slug {slug!r} already exists")

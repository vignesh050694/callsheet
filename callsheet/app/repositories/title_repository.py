"""Data access for titles. Queries only — no business rules, no HTTP."""

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.title import Title

_logger = structlog.get_logger(__name__)


class TitleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, title_id: uuid.UUID) -> Title | None:
        """Eager-loads terms and milestones.

        Both relationships are `lazy="raise"`, so this is not just an N+1 guard — the
        schedule update assigns to `title.milestones`, and assigning to an unloaded
        collection is what would raise.
        """
        _logger.debug("title.query.get_by_id", title_id=str(title_id))
        result = await self._session.execute(
            select(Title)
            .options(selectinload(Title.terms), selectinload(Title.milestones))
            .where(Title.id == title_id)
        )
        return result.scalar_one_or_none()

    async def list_for_organization(
        self, organization_id: uuid.UUID, *, limit: int, offset: int
    ) -> list[Title]:
        _logger.debug("title.query.list_for_organization", organization_id=str(organization_id))
        result = await self._session.execute(
            select(Title)
            .options(selectinload(Title.terms), selectinload(Title.milestones))
            .where(Title.organization_id == organization_id)
            .order_by(Title.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_for_organization(self, organization_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(Title).where(Title.organization_id == organization_id)
        )
        return int(result.scalar_one())

    async def add(self, title: Title) -> Title:
        self._session.add(title)
        await self._session.flush()
        return title

"""Data access for artists. Queries only — no business rules, no HTTP."""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.artist import Artist

_logger = structlog.get_logger(__name__)


class ArtistRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, artist_id: uuid.UUID) -> Artist | None:
        """Eager-loads the identity set: every caller renders the artist with their variants."""
        _logger.debug("artist.query.get_by_id", artist_id=str(artist_id))
        result = await self._session.execute(
            select(Artist).options(selectinload(Artist.terms)).where(Artist.id == artist_id)
        )
        return result.scalar_one_or_none()

    async def get_by_normalized_name(
        self, organization_id: uuid.UUID, normalized_name: str
    ) -> Artist | None:
        """Backs the reuse rule: tagging a known actor on a second title is not a new person."""
        _logger.debug(
            "artist.query.get_by_normalized_name",
            organization_id=str(organization_id),
            normalized_name=normalized_name,
        )
        result = await self._session.execute(
            select(Artist)
            .options(selectinload(Artist.terms))
            .where(
                Artist.organization_id == organization_id,
                Artist.normalized_name == normalized_name,
            )
        )
        return result.scalar_one_or_none()

    async def add(self, artist: Artist) -> Artist:
        self._session.add(artist)
        await self._session.flush()
        return artist

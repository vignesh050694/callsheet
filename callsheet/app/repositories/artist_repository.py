"""Data access for artists. Queries only — no business rules, no HTTP."""

import uuid
from typing import Any, cast

import structlog
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
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

    async def get_linked_to_user(self, artist_id: uuid.UUID, user_id: uuid.UUID) -> Artist | None:
        """Whether this account already holds the claim over this artist entity."""
        _logger.debug(
            "artist.query.get_linked_to_user", artist_id=str(artist_id), user_id=str(user_id)
        )
        result = await self._session.execute(
            select(Artist).where(Artist.id == artist_id, Artist.linked_user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def claim_for_user(self, artist_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Links the entity to an account only if nobody holds it. Returns whether this won.

        Conditional in the WHERE clause rather than checked in Python, because a
        check-then-assign cannot be made safe from the service layer: two concurrent
        accepts both read `linked_user_id IS NULL`, both assign, and the second UPDATE
        silently overwrites the first — no error, and the artist entity ends up bound to
        whoever committed last. `linked_user_id` cannot carry a unique constraint to
        arbitrate that, because one person legitimately holds one artist row per
        organization that tracks them, so the guard has to live in the write itself.

        Postgres serialises the two statements on the row lock, so the loser sees the
        winner's value and matches zero rows.
        """
        _logger.debug(
            "artist.command.claim_for_user", artist_id=str(artist_id), user_id=str(user_id)
        )
        # `AsyncSession.execute` is typed as returning `Result`, which has no rowcount —
        # an UPDATE always yields a `CursorResult`, and the count is the whole point here.
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                update(Artist)
                .where(Artist.id == artist_id, Artist.linked_user_id.is_(None))
                .values(linked_user_id=user_id)
            ),
        )
        return result.rowcount == 1

    async def add(self, artist: Artist) -> Artist:
        self._session.add(artist)
        await self._session.flush()
        return artist

"""Data access for title memberships. Queries only — no business rules, no HTTP."""

import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.artist import Artist
from app.models.title import Title
from app.models.title_membership import TitleMembership, TitleMembershipStatus

_logger = structlog.get_logger(__name__)


class TitleMembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_title(self, title_id: uuid.UUID) -> list[TitleMembership]:
        """Eager-loads the artist and their terms: the Members screen renders the person.

        Ordered by creation so the list does not reshuffle between reads — the same
        total-order reasoning the title identity set carries, and the ids break any tie.
        """
        _logger.debug("title_membership.query.list_for_title", title_id=str(title_id))
        result = await self._session.execute(
            select(TitleMembership)
            .options(
                selectinload(TitleMembership.artist).selectinload(Artist.terms),
                selectinload(TitleMembership.subject_organization),
            )
            .where(TitleMembership.title_id == title_id)
            .order_by(TitleMembership.created_at.asc(), TitleMembership.id.asc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, membership_id: uuid.UUID) -> TitleMembership | None:
        _logger.debug("title_membership.query.get_by_id", membership_id=str(membership_id))
        result = await self._session.execute(
            select(TitleMembership)
            .options(
                selectinload(TitleMembership.artist).selectinload(Artist.terms),
                selectinload(TitleMembership.subject_organization),
            )
            .where(TitleMembership.id == membership_id)
        )
        return result.scalar_one_or_none()

    async def get_for_title_and_artist(
        self, title_id: uuid.UUID, artist_id: uuid.UUID
    ) -> TitleMembership | None:
        _logger.debug(
            "title_membership.query.get_for_title_and_artist",
            title_id=str(title_id),
            artist_id=str(artist_id),
        )
        result = await self._session.execute(
            select(TitleMembership).where(
                TitleMembership.title_id == title_id,
                TitleMembership.artist_id == artist_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_by_token_hash(self, token_hash: str) -> TitleMembership | None:
        """Looks a live invitation up by the hash of the token its holder presents.

        Filtered to pending here rather than in the service, so an accepted or revoked
        membership is indistinguishable from a token that never existed — a redeemed
        link must not confirm to whoever replays it that it was once real.
        """
        _logger.debug("title_membership.query.get_pending_by_token_hash")
        result = await self._session.execute(
            select(TitleMembership)
            .options(
                selectinload(TitleMembership.artist).selectinload(Artist.terms),
                selectinload(TitleMembership.subject_organization),
            )
            .where(
                TitleMembership.token_hash == token_hash,
                TitleMembership.status == TitleMembershipStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_subject_user(
        self, title_id: uuid.UUID, user_id: uuid.UUID
    ) -> TitleMembership | None:
        """A live grant held by this person directly — an accepted artist tag."""
        _logger.debug(
            "title_membership.query.get_active_for_subject_user",
            title_id=str(title_id),
            user_id=str(user_id),
        )
        result = await self._session.execute(
            select(TitleMembership).where(
                TitleMembership.title_id == title_id,
                TitleMembership.subject_user_id == user_id,
                TitleMembership.status == TitleMembershipStatus.ACTIVE,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_subject_organizations(
        self, title_id: uuid.UUID, organization_ids: Sequence[uuid.UUID]
    ) -> TitleMembership | None:
        """A live grant reaching this caller through one of their organizations.

        `limit(1)` because the caller only needs to know whether a way in exists — a
        person in two organizations that were both granted the same title has one
        answer, not two, and both grants carry the same role.
        """
        _logger.debug(
            "title_membership.query.get_active_for_subject_organizations",
            title_id=str(title_id),
            organization_count=len(organization_ids),
        )
        result = await self._session.execute(
            select(TitleMembership)
            .where(
                TitleMembership.title_id == title_id,
                TitleMembership.subject_organization_id.in_(organization_ids),
                TitleMembership.status == TitleMembershipStatus.ACTIVE,
            )
            .order_by(TitleMembership.created_at.asc(), TitleMembership.id.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_active_titles_for_organizations(
        self, organization_ids: Sequence[uuid.UUID]
    ) -> list[Title]:
        """Titles shared with these organizations — the agency's client switcher.

        Strictly the granted titles and nothing else: this is the query that has to not
        leak the rest of the owning organization's slate.
        """
        _logger.debug(
            "title_membership.query.list_active_titles_for_organizations",
            organization_count=len(organization_ids),
        )
        if not organization_ids:
            return []
        result = await self._session.execute(
            select(Title)
            .join(TitleMembership, TitleMembership.title_id == Title.id)
            .options(selectinload(Title.terms), selectinload(Title.milestones))
            .where(
                TitleMembership.subject_organization_id.in_(organization_ids),
                TitleMembership.status == TitleMembershipStatus.ACTIVE,
            )
            .order_by(Title.release_date.desc(), Title.id.asc())
        )
        return list(result.scalars().all())

    async def list_active_titles_for_user(self, user_id: uuid.UUID) -> list[Title]:
        """The titles a signed-in non-owner may read, via an accepted title membership.

        Joined rather than loaded through the memberships, because the caller renders
        titles. Ordered by release date then id so the list is stable between reads —
        two titles sharing a release date can never swap places.
        """
        _logger.debug("title_membership.query.list_active_titles_for_user", user_id=str(user_id))
        result = await self._session.execute(
            select(Title)
            .join(TitleMembership, TitleMembership.title_id == Title.id)
            .options(selectinload(Title.terms), selectinload(Title.milestones))
            .where(
                TitleMembership.subject_user_id == user_id,
                TitleMembership.status == TitleMembershipStatus.ACTIVE,
            )
            .order_by(Title.release_date.desc(), Title.id.asc())
        )
        return list(result.scalars().all())

    async def add(self, membership: TitleMembership) -> TitleMembership:
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def delete(self, membership: TitleMembership) -> None:
        """Untagging removes the row outright — see `TitleMembershipService.untag_artist`."""
        await self._session.delete(membership)
        await self._session.flush()

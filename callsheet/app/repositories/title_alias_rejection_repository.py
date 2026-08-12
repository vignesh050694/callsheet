"""Data access for refused alias suggestions (E02-S04). Queries only — no rules."""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.title_alias_rejection import TitleAliasRejection

_logger = structlog.get_logger(__name__)


class TitleAliasRejectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def folded_values_for_title(self, title_id: uuid.UUID) -> set[str]:
        """Everything this title has already said no to, as the miner compares terms.

        Returned as a set rather than rows: the only question the mining path asks is
        membership, once per candidate, and it asks it thousands of times per corpus.
        """
        result = await self._session.execute(
            select(TitleAliasRejection.folded_value).where(TitleAliasRejection.title_id == title_id)
        )
        return set(result.scalars().all())

    async def get_by_id(self, rejection_id: uuid.UUID) -> TitleAliasRejection | None:
        return await self._session.get(TitleAliasRejection, rejection_id)

    async def get_for_title_and_value(
        self, title_id: uuid.UUID, folded_value: str
    ) -> TitleAliasRejection | None:
        result = await self._session.execute(
            select(TitleAliasRejection).where(
                TitleAliasRejection.title_id == title_id,
                TitleAliasRejection.folded_value == folded_value,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_title(self, title_id: uuid.UUID) -> list[TitleAliasRejection]:
        """Refused terms, newest first, so the screen can show and undo a decision.

        `created_at` alone is not a total order — it is a server default with one-second
        resolution on SQLite — so the id breaks ties and the list cannot reshuffle between
        two reads of unchanged data.
        """
        result = await self._session.execute(
            select(TitleAliasRejection)
            .where(TitleAliasRejection.title_id == title_id)
            .order_by(TitleAliasRejection.created_at.desc(), TitleAliasRejection.id)
        )
        return list(result.scalars().all())

    def add(self, rejection: TitleAliasRejection) -> None:
        self._session.add(rejection)
        _logger.debug("title_alias_rejection.query.add", title_id=str(rejection.title_id))

    async def delete(self, rejection: TitleAliasRejection) -> None:
        await self._session.delete(rejection)

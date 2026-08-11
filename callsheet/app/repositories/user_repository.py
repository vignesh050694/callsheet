"""Data access for users. Queries only — no business rules, no HTTP."""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

_logger = structlog.get_logger(__name__)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        _logger.debug("user.query.get_by_id", user_id=str(user_id))
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        _logger.debug("user.query.get_by_email")
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

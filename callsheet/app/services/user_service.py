"""Business logic for users and their org memberships (E01-S01).

Resolving the caller lives here rather than in the API layer so that "who is asking"
is a single, testable rule. Session and credential handling belong to the auth layer,
which v1's invite-led flow does not include.
"""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationRequiredError
from app.models.membership import Membership
from app.models.user import User
from app.repositories.membership_repository import MembershipRepository
from app.repositories.user_repository import UserRepository

_logger = structlog.get_logger(__name__)

UNKNOWN_CALLER_MESSAGE = "The caller could not be identified"


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._user_repository = UserRepository(session)
        self._membership_repository = MembershipRepository(session)

    async def resolve_caller(self, user_id: uuid.UUID | None) -> User:
        """Turn the caller's asserted identity into a user row, or refuse the request."""
        if user_id is None:
            _logger.warning("user.resolve.missing_identity")
            raise AuthenticationRequiredError(UNKNOWN_CALLER_MESSAGE)

        user = await self._user_repository.get_by_id(user_id)
        if user is None:
            # Deliberately the same message as a missing header: a caller probing for
            # valid user ids learns nothing from the difference.
            _logger.warning("user.resolve.unknown_user", user_id=str(user_id))
            raise AuthenticationRequiredError(UNKNOWN_CALLER_MESSAGE)

        return user

    async def list_memberships(self, user_id: uuid.UUID) -> list[Membership]:
        return await self._membership_repository.list_for_user(user_id)

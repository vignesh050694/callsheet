"""Shared FastAPI dependencies.

Controllers declare what they need here rather than constructing services inline, which
keeps route bodies to "parse input, call service, shape response".
"""

import uuid
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.user import User
from app.services.organization_service import OrganizationService
from app.services.user_service import UserService

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_organization_service(session: DbSession) -> OrganizationService:
    return OrganizationService(session)


OrganizationServiceDep = Annotated[OrganizationService, Depends(get_organization_service)]


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


async def get_current_user(
    user_service: UserServiceDep,
    x_user_id: Annotated[uuid.UUID | None, Header(alias="X-User-Id")] = None,
) -> User:
    """The caller, as asserted by `X-User-Id`.

    This is the seam a real session layer will replace. It is deliberately the only
    place the header is read, so swapping it out touches one function rather than
    every route that needs to know who is asking.
    """
    return await user_service.resolve_caller(x_user_id)


CurrentUser = Annotated[User, Depends(get_current_user)]

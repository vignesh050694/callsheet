"""Shared FastAPI dependencies.

Controllers declare what they need here rather than constructing services inline, which
keeps route bodies to "parse input, call service, shape response".
"""

import uuid
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db_session
from app.models.user import User
from app.services.collection.monid_source import (
    MonidCollectionSource,
    MonidTransport,
    UnconfiguredMonidTransport,
)
from app.services.collection.source import CollectionSource
from app.services.collection_service import CollectionService
from app.services.invitation_notifier import InvitationNotifier
from app.services.invitation_service import InvitationService
from app.services.organization_service import OrganizationService
from app.services.preview_search import PreviewSearch, UnconfiguredPreviewSearch
from app.services.title_preview_service import TitlePreviewService
from app.services.title_service import TitleService
from app.services.user_service import UserService

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_organization_service(session: DbSession) -> OrganizationService:
    return OrganizationService(session)


OrganizationServiceDep = Annotated[OrganizationService, Depends(get_organization_service)]


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


def get_invitation_notifier() -> InvitationNotifier:
    """Overridable seam: a test asserts against it, a real mailer replaces it."""
    return InvitationNotifier()


InvitationNotifierDep = Annotated[InvitationNotifier, Depends(get_invitation_notifier)]


def get_invitation_service(
    session: DbSession, notifier: InvitationNotifierDep
) -> InvitationService:
    return InvitationService(session, notifier)


InvitationServiceDep = Annotated[InvitationService, Depends(get_invitation_service)]


def get_title_service(session: DbSession) -> TitleService:
    return TitleService(session)


TitleServiceDep = Annotated[TitleService, Depends(get_title_service)]


def get_preview_search() -> PreviewSearch:
    """The seam the collection layer plugs into.

    Unconfigured by default: until E03 supplies an adapter there is no platform to
    search, and the preview says so instead of inventing a sample. A test binds a fake
    here the same way it binds the invitation notifier.
    """
    return UnconfiguredPreviewSearch()


PreviewSearchDep = Annotated[PreviewSearch, Depends(get_preview_search)]


def get_title_preview_service(
    session: DbSession, search: PreviewSearchDep
) -> TitlePreviewService:
    return TitlePreviewService(session, search)


TitlePreviewServiceDep = Annotated[TitlePreviewService, Depends(get_title_preview_service)]


def get_app_settings() -> Settings:
    """Settings as a dependency, so a test can point a platform at another endpoint."""
    return get_settings()


AppSettings = Annotated[Settings, Depends(get_app_settings)]


def get_monid_transport() -> MonidTransport:
    """The one seam that leaves the process.

    Unconfigured by default: the real Monid client, with its run polling and spend
    controls, arrives with E03-S01. Until then collection refuses rather than returning
    empty pages that would read as silence.
    """
    return UnconfiguredMonidTransport()


MonidTransportDep = Annotated[MonidTransport, Depends(get_monid_transport)]


def get_collection_source(
    transport: MonidTransportDep, settings: AppSettings
) -> CollectionSource:
    return MonidCollectionSource(transport, settings)


CollectionSourceDep = Annotated[CollectionSource, Depends(get_collection_source)]


def get_collection_service(
    session: DbSession, source: CollectionSourceDep
) -> CollectionService:
    return CollectionService(session, source)


CollectionServiceDep = Annotated[CollectionService, Depends(get_collection_service)]


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

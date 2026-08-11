"""Title routes.

Routing only: validate the request shape, call one service method, shape the response.
The anchor rule and every access check live in `TitleService`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, TitleServiceDep
from app.models.title import Title
from app.schemas.common import Page, PageParams
from app.schemas.title import TitleCreate, TitleRead, TitleTermRead
from app.services.title_service import TitleService

router = APIRouter(tags=["titles"])


def _to_title_read(title: Title) -> TitleRead:
    """Assembles the derived identity view the API promises, from one loaded title."""
    return TitleRead(
        id=title.id,
        organization_id=title.organization_id,
        name=title.name,
        poster_url=title.poster_url,
        terms=[TitleTermRead.model_validate(term) for term in title.terms],
        collection_terms=TitleService.collection_terms_for(title),
        has_anchor_term=TitleService.has_anchor_term(title),
        created_at=title.created_at,
        updated_at=title.updated_at,
    )


@router.post(
    "/organizations/{organization_id}/titles",
    response_model=TitleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a title with its identity set",
)
async def create_title(
    organization_id: uuid.UUID,
    payload: TitleCreate,
    title_service: TitleServiceDep,
    current_user: CurrentUser,
) -> TitleRead:
    title = await title_service.create_title(organization_id, payload, current_user)
    return _to_title_read(title)


@router.get(
    "/organizations/{organization_id}/titles",
    response_model=Page[TitleRead],
    summary="List the organization's titles",
)
async def list_titles(
    organization_id: uuid.UUID,
    title_service: TitleServiceDep,
    current_user: CurrentUser,
    page_params: Annotated[PageParams, Query()],
) -> Page[TitleRead]:
    titles, total_count = await title_service.list_titles(
        organization_id,
        current_user,
        limit=page_params.limit,
        offset=page_params.offset,
    )
    return Page[TitleRead](
        items=[_to_title_read(title) for title in titles],
        total=total_count,
        limit=page_params.limit,
        offset=page_params.offset,
    )


@router.get(
    "/titles/{title_id}",
    response_model=TitleRead,
    summary="Fetch a single title",
)
async def read_title(
    title_id: uuid.UUID,
    title_service: TitleServiceDep,
    current_user: CurrentUser,
) -> TitleRead:
    title = await title_service.get_title(title_id, current_user)
    return _to_title_read(title)

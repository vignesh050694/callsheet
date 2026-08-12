"""Title routes.

Routing only: validate the request shape, call one service method, shape the response.
The anchor rule and every access check live in `TitleService`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, TitleServiceDep
from app.core.release_phase import phase_for_date
from app.models.title import Title
from app.schemas.common import Page, PageParams
from app.schemas.title import (
    TitleCreate,
    TitleMilestoneRead,
    TitleRead,
    TitleScheduleUpdate,
    TitleTermRead,
)
from app.services.title_service import TitleService

router = APIRouter(tags=["titles"])


def _to_title_read(title: Title) -> TitleRead:
    """Assembles the derived identity view the API promises, from one loaded title."""
    return TitleRead(
        id=title.id,
        organization_id=title.organization_id,
        name=title.name,
        release_date=title.release_date,
        milestones=[
            TitleMilestoneRead(
                id=milestone.id,
                name=milestone.name,
                occurs_on=milestone.occurs_on,
                # Derived here, against the release date as it stands right now. Move the
                # release date and every milestone re-sorts itself across the boundary on
                # the next read, with nothing rewritten.
                phase=phase_for_date(milestone.occurs_on, title.release_date),
            )
            for milestone in TitleService.milestones_in_order(title)
        ],
        poster_url=title.poster_url,
        # Sorted here rather than trusted from the ORM, for the same reason the milestones
        # above are: the relationship's `order_by` does not apply when the collection is
        # already loaded, so a POST response would come back in insertion order while an
        # independent GET of the same title came back sorted.
        terms=[TitleTermRead.model_validate(term) for term in TitleService.terms_in_order(title)],
        collection_terms=TitleService.collection_terms_for(title),
        excluded_terms=TitleService.excluded_terms_for(title),
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


@router.put(
    "/titles/{title_id}/schedule",
    response_model=TitleRead,
    summary="Set the release date and campaign milestones",
)
async def replace_title_schedule(
    title_id: uuid.UUID,
    payload: TitleScheduleUpdate,
    title_service: TitleServiceDep,
    current_user: CurrentUser,
) -> TitleRead:
    """PUT rather than PATCH: the milestone list is replaced wholesale.

    An editable list in a form has to be able to shrink, and a partial update has no way
    to say "this row is gone". The schedule is its own sub-resource for the same reason —
    it is the one part of a title that changes on its own, without the identity set.
    """
    title = await title_service.replace_schedule(title_id, payload, current_user)
    return _to_title_read(title)

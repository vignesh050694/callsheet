"""Organization routes.

Routing only: validate the request shape, call one service method, shape the response.
Business rules live in `OrganizationService`; queries live in `OrganizationRepository`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import OrganizationServiceDep
from app.schemas.common import Page, PageParams
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post(
    "",
    response_model=OrganizationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an organization",
)
async def create_organization(
    payload: OrganizationCreate,
    organization_service: OrganizationServiceDep,
) -> OrganizationRead:
    organization = await organization_service.create_organization(payload)
    return OrganizationRead.model_validate(organization)


@router.get("", response_model=Page[OrganizationRead], summary="List organizations")
async def list_organizations(
    organization_service: OrganizationServiceDep,
    page_params: Annotated[PageParams, Query()],
) -> Page[OrganizationRead]:
    organizations, total_count = await organization_service.list_organizations(
        limit=page_params.limit,
        offset=page_params.offset,
    )
    return Page[OrganizationRead](
        items=[OrganizationRead.model_validate(item) for item in organizations],
        total=total_count,
        limit=page_params.limit,
        offset=page_params.offset,
    )


@router.get(
    "/{organization_id}",
    response_model=OrganizationRead,
    summary="Fetch a single organization",
)
async def read_organization(
    organization_id: uuid.UUID,
    organization_service: OrganizationServiceDep,
) -> OrganizationRead:
    organization = await organization_service.get_organization(organization_id)
    return OrganizationRead.model_validate(organization)


@router.patch(
    "/{organization_id}",
    response_model=OrganizationRead,
    summary="Update an organization",
)
async def update_organization(
    organization_id: uuid.UUID,
    payload: OrganizationUpdate,
    organization_service: OrganizationServiceDep,
) -> OrganizationRead:
    organization = await organization_service.update_organization(organization_id, payload)
    return OrganizationRead.model_validate(organization)


@router.delete(
    "/{organization_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an organization",
)
async def delete_organization(
    organization_id: uuid.UUID,
    organization_service: OrganizationServiceDep,
) -> None:
    await organization_service.delete_organization(organization_id)

"""Request/response DTOs for organizations. These never leak ORM objects to the API."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.organization import (
    ORGANIZATION_NAME_MAX_LENGTH,
    ORGANIZATION_SLUG_MAX_LENGTH,
    OrganizationType,
)

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=ORGANIZATION_NAME_MAX_LENGTH)
    slug: str = Field(
        min_length=2,
        max_length=ORGANIZATION_SLUG_MAX_LENGTH,
        pattern=SLUG_PATTERN,
        description="URL-safe identifier, lowercase and hyphen-separated.",
    )
    organization_type: OrganizationType = OrganizationType.PRODUCTION_HOUSE


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=ORGANIZATION_NAME_MAX_LENGTH)
    organization_type: OrganizationType | None = None


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    organization_type: OrganizationType
    created_at: datetime
    updated_at: datetime

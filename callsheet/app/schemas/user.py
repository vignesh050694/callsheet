"""Request/response DTOs for users and their memberships."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.membership import MembershipRole
from app.schemas.organization import OrganizationRead


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    is_email_verified: bool
    created_at: datetime
    updated_at: datetime


class MembershipRead(BaseModel):
    """A membership always travels with its organization — a bare role is not actionable."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MembershipRole
    organization: OrganizationRead
    created_at: datetime


class CurrentUserRead(BaseModel):
    """What the signed-in user needs on first paint: who they are and where they belong.

    An empty `memberships` list is what sends a first-time user to onboarding, so it is
    always present rather than omitted.
    """

    user: UserRead
    memberships: list[MembershipRead]

"""Request/response DTOs for invitations and the Members screen."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.models.invitation import InvitationStatus
from app.models.membership import MembershipRole


class InvitationCreate(BaseModel):
    email: EmailStr
    role: MembershipRole

    @field_validator("email")
    @classmethod
    def normalize_email(cls, raw_email: str) -> str:
        """Stored lowercased so `A@b.com` and `a@b.com` cannot both hold an invite."""
        return raw_email.strip().lower()


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: MembershipRole
    status: InvitationStatus
    last_sent_at: datetime
    created_at: datetime


class InvitationCreated(InvitationRead):
    """Carries the raw token exactly once, on the response that mints it.

    v1 has no mail transport, so the acceptance link has to reach the caller somehow;
    this is the seam a real mailer replaces.
    """

    token: str


class InvitationAccept(BaseModel):
    token: str


class MemberRead(BaseModel):
    """A person who already holds a membership, as shown on the Members screen."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    email: str
    display_name: str
    role: MembershipRole
    joined_at: datetime


class MembersView(BaseModel):
    """Everything the Members screen renders: who is in, and who has been asked."""

    members: list[MemberRead]
    pending_invitations: list[InvitationRead]

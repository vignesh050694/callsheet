"""Invitation table — a pending offer of membership in an organization (E01-S02).

An invitation is a capability: whoever holds its token can claim the membership. Only a
hash of that token is stored, so a leaked database does not hand over every open invite.
The raw token exists once, in the email that carries it.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.membership import MembershipRole
from app.models.organization import Organization
from app.models.user import User

INVITATION_EMAIL_MAX_LENGTH = 320
INVITATION_TOKEN_HASH_LENGTH = 64


class InvitationStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"


class Invitation(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "invitations"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(INVITATION_EMAIL_MAX_LENGTH), nullable=False)
    role: Mapped[MembershipRole] = mapped_column(
        SqlEnum(MembershipRole, name="membership_role", native_enum=False),
        nullable=False,
    )
    status: Mapped[InvitationStatus] = mapped_column(
        SqlEnum(InvitationStatus, name="invitation_status", native_enum=False),
        nullable=False,
        default=InvitationStatus.PENDING,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(INVITATION_TOKEN_HASH_LENGTH),
        nullable=False,
        unique=True,
        index=True,
    )
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    organization: Mapped[Organization] = relationship(lazy="raise")
    invited_by: Mapped[User] = relationship(lazy="raise")

    @property
    def is_pending(self) -> bool:
        return self.status is InvitationStatus.PENDING

    def __repr__(self) -> str:
        return f"<Invitation id={self.id} email={self.email!r} status={self.status}>"

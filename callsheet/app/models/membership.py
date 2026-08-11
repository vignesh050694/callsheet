"""Membership table — the join that grants a user a role in an organization (E01-S01).

Ownership is a membership row rather than a column on `organizations`, so it can be
transferred or held by more than one person without a schema change. Roles beyond
`owner` arrive with the stories that introduce them.
"""

import enum
import uuid

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.organization import Organization
from app.models.user import User


class MembershipRole(enum.StrEnum):
    OWNER = "owner"
    VIEWER = "viewer"

    @property
    def can_administer_organization(self) -> bool:
        """Owners administer; viewers read. Enforced in the service layer, never in the UI alone."""
        return self is MembershipRole.OWNER


class Membership(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organization_id", name="uq_membership_user_organization"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MembershipRole] = mapped_column(
        SqlEnum(MembershipRole, name="membership_role", native_enum=False),
        nullable=False,
    )

    user: Mapped[User] = relationship(lazy="raise")
    organization: Mapped[Organization] = relationship(lazy="raise")

    def __repr__(self) -> str:
        return f"<Membership user_id={self.user_id} organization_id={self.organization_id}>"

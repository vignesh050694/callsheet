"""Access audit log — who granted or revoked what, and when (E01-S05, E01-S06).

Append-only by convention: rows are written when access changes and never updated or
deleted. The story asks for it on grants; revocation (E01-S06) writes to the same table,
because "when did this agency get access and when did it end" is one question and
answering it from two places invites the two to disagree.

Deliberately not derived from `title_memberships`. That table holds *current* state — a
revoked grant that is later re-issued overwrites its own history, and a deleted membership
takes its history with it. An engagement that ended is exactly the case someone will need
to reconstruct later, so the event is recorded separately from the state it changed.

The subject is stored as denormalised identifiers plus a display name rather than as a
foreign key alone: the point of an audit row is to still make sense after the thing it
refers to is gone.
"""

import enum
import uuid

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.title_membership import TitleRole

AUDIT_SUBJECT_NAME_MAX_LENGTH = 300


class AccessAuditAction(enum.StrEnum):
    GRANTED = "granted"
    REVOKED = "revoked"


class AccessAuditEvent(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One change to who can see a title.

    `created_at` from `TimestampMixin` is the timestamp the story asks for; there is no
    separate `occurred_at`, because the row is written in the same transaction as the
    change it records and two clocks would only ever drift apart.
    """

    __tablename__ = "access_audit_events"

    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[AccessAuditAction] = mapped_column(
        SqlEnum(AccessAuditAction, name="access_audit_action", native_enum=False),
        nullable=False,
    )
    role: Mapped[TitleRole] = mapped_column(
        SqlEnum(TitleRole, name="title_role", native_enum=False),
        nullable=False,
    )
    # Who performed the change. Not nullable: an access change with no actor is not
    # auditable, and there is no path that makes one without a signed-in caller.
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # The scope: which organization or person gained or lost access. One of the two is
    # set, matching the membership's own subject.
    subject_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
    )
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
        index=True,
    )
    # Kept as text so the row still reads after the organization or artist is deleted.
    subject_name: Mapped[str] = mapped_column(
        String(AUDIT_SUBJECT_NAME_MAX_LENGTH),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<AccessAuditEvent {self.action} role={self.role} title_id={self.title_id}>"

"""User table — the person behind a membership (E01-S01).

Users arrive through pilot invitation, so this table records identity only: who they
are and whether their email has been verified. Credentials and sessions belong to the
auth layer, which is not part of v1's invite-led flow.
"""

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

USER_EMAIL_MAX_LENGTH = 320
USER_DISPLAY_NAME_MAX_LENGTH = 200


class User(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(USER_EMAIL_MAX_LENGTH),
        nullable=False,
        unique=True,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(
        String(USER_DISPLAY_NAME_MAX_LENGTH),
        nullable=False,
    )
    is_email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"

"""Organization table — the root every title, artist, and membership hangs off (E01-S01)."""

import enum

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin

ORGANIZATION_NAME_MAX_LENGTH = 200
ORGANIZATION_SLUG_MAX_LENGTH = 120


class OrganizationType(enum.StrEnum):
    PRODUCTION_HOUSE = "production_house"
    AGENCY = "agency"


class Organization(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(ORGANIZATION_NAME_MAX_LENGTH), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(ORGANIZATION_SLUG_MAX_LENGTH),
        nullable=False,
        unique=True,
        index=True,
    )
    organization_type: Mapped[OrganizationType] = mapped_column(
        SqlEnum(OrganizationType, name="organization_type", native_enum=False),
        nullable=False,
        default=OrganizationType.PRODUCTION_HOUSE,
    )

    def __repr__(self) -> str:
        return f"<Organization id={self.id} slug={self.slug!r}>"

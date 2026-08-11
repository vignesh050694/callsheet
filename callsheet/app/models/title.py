"""Title tables — a film or show, and the identity set collection queries against (E02-S01).

The identity set is one table rather than a column per field. A bare title name is the
known failure case: collection against the name alone returns everything that shares it,
while the anchored form — name plus aliases, hashtags, and the people attached to it —
is what actually finds the film. Storing every term in one place means "query the whole
identity set" is a single read, and adding a term kind later is a row, not a migration
of consumers.
"""

import enum
import uuid

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.organization import Organization

TITLE_NAME_MAX_LENGTH = 300
TITLE_TERM_MAX_LENGTH = 300
POSTER_URL_MAX_LENGTH = 2048

# A name this short is not collectable on its own — it needs a person to anchor it.
MIN_UNANCHORED_NAME_LENGTH = 4


class TitleTermType(enum.StrEnum):
    ALIAS = "alias"
    HASHTAG = "hashtag"
    CAST = "cast"
    DIRECTOR = "director"
    MUSIC_DIRECTOR = "music_director"

    @property
    def is_anchor(self) -> bool:
        """People anchor a query. A hashtag can be as generic as the name it accompanies."""
        return self in _ANCHOR_TERM_TYPES


_ANCHOR_TERM_TYPES = frozenset(
    {TitleTermType.CAST, TitleTermType.DIRECTOR, TitleTermType.MUSIC_DIRECTOR}
)


class Title(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "titles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(TITLE_NAME_MAX_LENGTH), nullable=False)
    poster_url: Mapped[str | None] = mapped_column(
        String(POSTER_URL_MAX_LENGTH),
        nullable=True,
    )

    organization: Mapped[Organization] = relationship(lazy="raise")
    terms: Mapped[list["TitleTerm"]] = relationship(
        back_populates="title",
        lazy="raise",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Title id={self.id} name={self.name!r}>"


class TitleTerm(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One entry in a title's identity set.

    `value` is what the studio typed and what the UI shows back. `normalized_value` is
    the comparable form — it is what dedupes the set and what collection matches on, so
    "#Vaaranam" and "vaaranam" cannot both occupy the set as if they were different.
    """

    __tablename__ = "title_terms"
    __table_args__ = (
        UniqueConstraint(
            "title_id",
            "term_type",
            "normalized_value",
            name="uq_title_term_normalized",
        ),
    )

    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    term_type: Mapped[TitleTermType] = mapped_column(
        SqlEnum(TitleTermType, name="title_term_type", native_enum=False),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(TITLE_TERM_MAX_LENGTH), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(TITLE_TERM_MAX_LENGTH), nullable=False)

    title: Mapped[Title] = relationship(back_populates="terms", lazy="raise")

    def __repr__(self) -> str:
        return f"<TitleTerm {self.term_type}={self.value!r}>"

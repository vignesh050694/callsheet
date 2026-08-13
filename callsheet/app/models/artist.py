"""Artist tables — a person a title's coverage can be about (E01-S03).

An artist is an *entity*, not a user. The production house creates one by tagging someone
on a title, long before that person has an account — and they may never get one. Keeping
the entity separate from `users` is what lets collection match mentions of an actor whose
invitation is still pending, and it is what E01-S04 links an account onto rather than
creating identity from scratch.

The identity set mirrors `title_terms` for the same reason that one exists: a bare display
name is not matchable. "Anirudh" appears in every third film discussion; "Anirudh
Ravichandran" plus the handles he posts under is what actually finds him. Storing every
spelling in one table means "who is this artist, by any name" is a single read.
"""

import enum
import uuid

from sqlalchemy import Enum as SqlEnum
from sqlalchemy import ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.organization import Organization
from app.models.user import User

ARTIST_NAME_MAX_LENGTH = 200
ARTIST_TERM_MAX_LENGTH = 300
ARTIST_PLATFORM_MAX_LENGTH = 40


class ArtistTermType(enum.StrEnum):
    """The two ways an artist is named in a post."""

    NAME_VARIANT = "name_variant"
    HANDLE = "handle"

    @property
    def is_handle(self) -> bool:
        """A handle carries a platform; a name variant does not."""
        return self is ArtistTermType.HANDLE


def artist_term_sort_key(term: "ArtistIdentityTerm") -> tuple[str, str]:
    """The one canonical order for an artist's identity terms.

    Same reasoning as `identity_term_sort_key` on titles: more than one place produces
    this list — the relationship's `order_by` and the API response — and any two of them
    disagreeing shows up as variants moving around on screen between saving a tag and
    re-reading it. `uq_artist_term_normalized` makes the pair unique, so this never ties.
    """
    return (term.term_type.name, term.normalized_value)


class Artist(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """A named person the production house tracks coverage for.

    Scoped to the organization that created the record. Two production houses tagging the
    same actor get two artist rows, which is deliberate for v1: merging them would mean
    deciding that two similarly-named people are the same person, and identity in v1 is
    claimed by invitation only (concept note risk #7), never inferred.
    """

    __tablename__ = "artists"
    __table_args__ = (
        # One artist per name per organization. Tagging the same actor on a second title
        # reuses this row rather than forking their identity set in two.
        UniqueConstraint(
            "organization_id",
            "normalized_name",
            name="uq_artist_organization_normalized_name",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(String(ARTIST_NAME_MAX_LENGTH), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(ARTIST_NAME_MAX_LENGTH), nullable=False)
    # Set when the artist accepts an invitation and claims the entity (E01-S04). Null
    # until then, which is the normal state — the production house creates the entity
    # long before the person it describes has an account, and may never link one.
    #
    # This is the whole of identity verification in v1 (concept note risk #7): the claim
    # is made by redeeming an invitation addressed to a verified email, never inferred
    # from a matching name.
    linked_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    organization: Mapped[Organization] = relationship(lazy="raise")
    linked_user: Mapped[User | None] = relationship(lazy="raise")
    terms: Mapped[list["ArtistIdentityTerm"]] = relationship(
        back_populates="artist",
        lazy="raise",
        cascade="all, delete-orphan",
        # A total order, for the reason `Title.terms` documents: SQL returns rows in no
        # defined order, so two reads of an unchanged identity set can hand them back
        # differently. `uq_artist_term_normalized` guarantees this never ties.
        order_by="ArtistIdentityTerm.term_type, ArtistIdentityTerm.normalized_value",
    )

    def __repr__(self) -> str:
        return f"<Artist id={self.id} display_name={self.display_name!r}>"


class ArtistIdentityTerm(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One spelling or handle that means this artist.

    `value` is what was typed and what the UI shows back. `normalized_value` is the
    comparable form — what dedupes the set and what entity matching runs against — so
    "@Anirudh_R" and "anirudh_r" cannot both sit in the set as if they were two people.
    """

    __tablename__ = "artist_identity_terms"
    __table_args__ = (
        UniqueConstraint(
            "artist_id",
            "term_type",
            "normalized_value",
            name="uq_artist_term_normalized",
        ),
    )

    artist_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("artists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    term_type: Mapped[ArtistTermType] = mapped_column(
        SqlEnum(ArtistTermType, name="artist_term_type", native_enum=False),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(ARTIST_TERM_MAX_LENGTH), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(ARTIST_TERM_MAX_LENGTH), nullable=False)
    # Which network the handle belongs to. Null for a name variant, which is not
    # platform-specific — the same spelling of a name matches on every platform.
    platform: Mapped[str | None] = mapped_column(
        String(ARTIST_PLATFORM_MAX_LENGTH),
        nullable=True,
    )

    artist: Mapped[Artist] = relationship(back_populates="terms", lazy="raise")

    def __repr__(self) -> str:
        return f"<ArtistIdentityTerm {self.term_type}={self.value!r}>"

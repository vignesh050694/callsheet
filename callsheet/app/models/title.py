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
from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.organization import Organization

TITLE_NAME_MAX_LENGTH = 300
TITLE_TERM_MAX_LENGTH = 300
POSTER_URL_MAX_LENGTH = 2048
MILESTONE_NAME_MAX_LENGTH = 120

# A name this short is not collectable on its own — it needs a person to anchor it.
MIN_UNANCHORED_NAME_LENGTH = 4


class TitleTermType(enum.StrEnum):
    ALIAS = "alias"
    HASHTAG = "hashtag"
    CAST = "cast"
    DIRECTOR = "director"
    MUSIC_DIRECTOR = "music_director"
    # A term that disqualifies a post rather than qualifying it (E02-S03 seeds these from
    # the preview; E02-S05 is where they are managed against collected mentions). It sits
    # in the same table because it is part of the same decision — what counts as this
    # title — and keeping it here means one read answers that question in full.
    EXCLUSION = "exclusion"

    @property
    def is_anchor(self) -> bool:
        """People anchor a query. A hashtag can be as generic as the name it accompanies."""
        return self in _ANCHOR_TERM_TYPES

    @property
    def is_exclusion(self) -> bool:
        """Negative terms never widen a query — they narrow what the results may contain."""
        return self is TitleTermType.EXCLUSION


_ANCHOR_TERM_TYPES = frozenset(
    {TitleTermType.CAST, TitleTermType.DIRECTOR, TitleTermType.MUSIC_DIRECTOR}
)


def identity_term_sort_key(term: "TitleTerm") -> tuple[str, str]:
    """The one canonical order for a title's identity terms.

    Defined once and used everywhere the list is produced, because there are three places
    that produce it — the relationship's `order_by`, the API response, and the collection
    query plan — and any two of them disagreeing is a bug that shows up as terms moving
    around on screen or a title's query set churning on its own.

    `term_type` leads and sorts on its *stored* form, which is the enum member name, so
    CAST precedes DIRECTOR precedes MUSIC_DIRECTOR — the anchor precedence the setup
    preview showed the studio. `uq_title_term_normalized` makes the pair unique per title,
    so this never ties.
    """
    return (term.term_type.name, term.normalized_value)


class Title(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "titles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(TITLE_NAME_MAX_LENGTH), nullable=False)
    # Required, because it is the boundary every chart splits on (E02-S02). A title with
    # no release date produces time-series nobody can read as before-vs-after, which is
    # the one comparison the product is built around.
    release_date: Mapped[date] = mapped_column(Date, nullable=False)
    poster_url: Mapped[str | None] = mapped_column(
        String(POSTER_URL_MAX_LENGTH),
        nullable=True,
    )

    organization: Mapped[Organization] = relationship(lazy="raise")
    terms: Mapped[list["TitleTerm"]] = relationship(
        back_populates="title",
        lazy="raise",
        cascade="all, delete-orphan",
        # A total order, for the same reason the milestones below have one, and with the
        # same consequence when it is missing: SQL returns rows in no defined order, so
        # two reads of an unchanged identity set can hand them back differently.
        #
        # This became load-bearing with E03-S01. Collection builds its query variants from
        # this list — the first anchor term in it becomes the person who anchors the title's
        # own query, and the plan is capped, so row order decides both *what* is asked and
        # *which* variants exist at all. Attribution keys are then stored against every
        # mention found. Unordered, a title's variant set could churn between cycles with
        # nothing changed by the studio, and alias discovery (E02-S04) would read that churn
        # as terms starting and stopping working.
        #
        # `uq_title_term_normalized` makes (term_type, normalized_value) unique per title,
        # so this can never tie. Term type leads, and its stored form sorts CAST before
        # DIRECTOR before MUSIC_DIRECTOR — the same precedence the setup preview used when
        # it showed the studio which anchor their sample was collected with (E02-S03).
        order_by="TitleTerm.term_type, TitleTerm.normalized_value",
    )
    milestones: Mapped[list["TitleMilestone"]] = relationship(
        back_populates="title",
        lazy="raise",
        cascade="all, delete-orphan",
        # `uq_title_milestone_name_date` makes (occurs_on, normalized_name) unique, so this
        # is a total order — two markers on the same day can never tie and swap places
        # between reads. Ordering on the normalised name rather than the display one means
        # retyping "trailer" as "Trailer" does not reshuffle the timeline.
        order_by="TitleMilestone.occurs_on, TitleMilestone.normalized_name",
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


class TitleMilestone(Base, UuidPrimaryKeyMixin, TimestampMixin):
    """One campaign beat — teaser, trailer, audio launch, bookings open (E02-S02).

    Free-text rather than a fixed enum: campaign beats differ by film and by language
    industry, and a studio that cannot record "single 2 drop" will record it in the name
    of something else instead. These are the reference points spike detection explains
    itself against later (E04-S05), so what matters is that the date is right, not that
    the label came from a list we wrote.

    `normalized_name` exists only to back the uniqueness constraint — unlike a title term
    it is never queried against, because a milestone is a marker on an axis, not something
    collection matches on.
    """

    __tablename__ = "title_milestones"
    __table_args__ = (
        # The same beat on the same day twice is a double-submit, not two markers.
        # Two beats sharing a name on *different* days are legitimate, so the date is
        # part of the key.
        UniqueConstraint(
            "title_id",
            "normalized_name",
            "occurs_on",
            name="uq_title_milestone_name_date",
        ),
    )

    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(MILESTONE_NAME_MAX_LENGTH), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        String(MILESTONE_NAME_MAX_LENGTH),
        nullable=False,
    )
    occurs_on: Mapped[date] = mapped_column(Date, nullable=False)

    title: Mapped[Title] = relationship(back_populates="milestones", lazy="raise")

    def __repr__(self) -> str:
        return f"<TitleMilestone {self.name!r} on {self.occurs_on}>"

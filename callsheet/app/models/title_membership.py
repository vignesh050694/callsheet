"""Title membership — access granted on a single title rather than a whole organization
(E01-S03).

`memberships` grants a role across an organization: an owner owns everything the org owns.
That is the wrong shape for the two people this epic still has to let in. A tagged artist
is not in the production house at all, and an agency is its own organization that must see
one film and not the slate behind it. Both are access to *one entity*, so both are a row
here rather than a widened org role.

The row is its own invitation. A pending membership carries the capability token that
turns it into an accepted one (E01-S04), which keeps "who has been offered access" and
"who has access" as one question with one answer — a separate invitations table would let
the two disagree, and the Members screen has to show both states side by side.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.artist import Artist
from app.models.base import Base, TimestampMixin, UuidPrimaryKeyMixin
from app.models.organization import Organization
from app.models.title import Title
from app.models.user import User

TITLE_MEMBERSHIP_EMAIL_MAX_LENGTH = 320
TITLE_MEMBERSHIP_HANDLE_MAX_LENGTH = 300
TITLE_MEMBERSHIP_TOKEN_HASH_LENGTH = 64


class TitleRole(enum.StrEnum):
    """The non-owner roles the concept note's access model names.

    Both members are declared here rather than one per story, because the pair *is* the
    access model (concept note §4) and the stored form is a VARCHAR with a check
    constraint — widening it later is a migration of the constraint, not a column.
    `AGENCY_MANAGER` is granted by E01-S05; nothing issues it before then.
    """

    TAGGED_ARTIST = "tagged_artist"
    AGENCY_MANAGER = "agency_manager"

    @property
    def can_see_only_mentions_naming_subject(self) -> bool:
        """A tagged artist sees the slice of the title's coverage that is about them.

        This is the restriction the tagging screen promises the owner and the acceptance
        flow promises the artist. It is a property of the role so that the promise and
        the enforcement read from one place instead of drifting apart.
        """
        return self is TitleRole.TAGGED_ARTIST

    @property
    def can_edit_title_setup(self) -> bool:
        """Neither role edits setup. Reading and exporting is the whole grant."""
        return False


class TitleMembershipStatus(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"

    @property
    def has_access(self) -> bool:
        """Only an accepted, unrevoked membership exposes anything.

        Pending is deliberately not access: the offer has been made and no data has moved.
        """
        return self is TitleMembershipStatus.ACTIVE


class TitleMembership(Base, UuidPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "title_memberships"
    __table_args__ = (
        # Tagging the same artist on the same title twice is a double-submit, not a second
        # membership. Untagging deletes the row, so re-tagging after a removal is allowed.
        UniqueConstraint("title_id", "artist_id", name="uq_title_membership_artist"),
        # A tagged artist is identified by an artist entity; the role and the subject must
        # agree, or a row could grant artist-shaped access to nothing at all.
        # `SqlEnum` persists the member *name*, not the value, so the literal here is
        # 'TAGGED_ARTIST' — matching against 'tagged_artist' would never fire and the
        # constraint would silently permit exactly what it exists to forbid.
        CheckConstraint(
            "(role != 'TAGGED_ARTIST') OR (artist_id IS NOT NULL)",
            name="ck_title_membership_artist_subject",
        ),
        # The mirror of the rule above: an agency grant is held by an organization, not a
        # person. Without this a grant could name nobody and still confer access.
        CheckConstraint(
            "(role != 'AGENCY_MANAGER') OR (subject_organization_id IS NOT NULL)",
            name="ck_title_membership_agency_subject",
        ),
        # One grant per organization per title. Re-sharing a title already shared is a
        # double-submit, not a second grant.
        UniqueConstraint(
            "title_id",
            "subject_organization_id",
            name="uq_title_membership_organization",
        ),
        # An artist invitation has to be reachable: without either channel the token can
        # never be delivered and the row sits pending forever with no way to act on it.
        # Scoped to the artist role, because an agency grant is not an invitation — the
        # organization is already on the platform and access starts immediately, so there
        # is nothing to send and no address to send it to.
        CheckConstraint(
            "(role != 'TAGGED_ARTIST') "
            "OR (invited_email IS NOT NULL) OR (invited_handle IS NOT NULL)",
            name="ck_title_membership_has_contact",
        ),
    )

    title_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("titles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artist_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("artists.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    role: Mapped[TitleRole] = mapped_column(
        SqlEnum(TitleRole, name="title_role", native_enum=False),
        nullable=False,
    )
    status: Mapped[TitleMembershipStatus] = mapped_column(
        SqlEnum(TitleMembershipStatus, name="title_membership_status", native_enum=False),
        nullable=False,
        default=TitleMembershipStatus.PENDING,
        index=True,
    )
    # Where the invitation was addressed. Email is the redeemable channel — acceptance
    # matches the redeemer's verified address against it (E01-S04). A handle-only tag
    # records who was meant to receive it, and the owner passes the link on by hand,
    # which is the same carried limitation E01-S02 has while there is no mail transport.
    invited_email: Mapped[str | None] = mapped_column(
        String(TITLE_MEMBERSHIP_EMAIL_MAX_LENGTH),
        nullable=True,
    )
    invited_handle: Mapped[str | None] = mapped_column(
        String(TITLE_MEMBERSHIP_HANDLE_MAX_LENGTH),
        nullable=True,
    )
    # Only the hash is stored, for the reason `app.core.tokens` documents: a leaked
    # database must not hand over a live credential. Null once the row is no longer
    # redeemable, so an accepted membership cannot be claimed a second time.
    token_hash: Mapped[str | None] = mapped_column(
        String(TITLE_MEMBERSHIP_TOKEN_HASH_LENGTH),
        nullable=True,
        unique=True,
        index=True,
    )
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Who redeemed the invitation (E01-S04). Null while the membership is pending — the
    # offer exists before there is an account behind it. This, not `artist_id`, is what
    # answers "which titles may this signed-in person read".
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # The agency organization a title is shared with (E01-S05). Access follows the
    # organization rather than the individual, because agency staff change mid-engagement
    # and re-inviting each new account by hand is how a former employee keeps access.
    subject_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # When the invitation was last issued. Null for an agency grant, which is never sent —
    # recording a send time for a message that does not exist would put a falsehood in the
    # one table access questions get answered from.
    last_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    title: Mapped[Title] = relationship(lazy="raise")
    artist: Mapped[Artist | None] = relationship(lazy="raise")
    subject_organization: Mapped[Organization | None] = relationship(lazy="raise")
    # Two foreign keys point at `users`, so each relationship has to say which one it
    # follows — SQLAlchemy cannot infer the join otherwise.
    invited_by: Mapped[User] = relationship(lazy="raise", foreign_keys=[invited_by_user_id])
    subject_user: Mapped[User | None] = relationship(lazy="raise", foreign_keys=[subject_user_id])

    @property
    def is_pending(self) -> bool:
        return self.status is TitleMembershipStatus.PENDING

    @property
    def has_access(self) -> bool:
        return self.status.has_access

    def __repr__(self) -> str:
        return f"<TitleMembership title_id={self.title_id} role={self.role} status={self.status}>"

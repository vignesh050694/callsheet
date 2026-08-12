"""Request/response DTOs for tagging artists on a title (E01-S03)."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.core.identity_terms import has_meaningful_content
from app.models.access_audit import AccessAuditAction
from app.models.artist import (
    ARTIST_NAME_MAX_LENGTH,
    ARTIST_PLATFORM_MAX_LENGTH,
    ARTIST_TERM_MAX_LENGTH,
    ArtistTermType,
)
from app.models.title_membership import TitleMembershipStatus, TitleRole

MAX_VARIANTS_PER_ARTIST = 50
MAX_HANDLES_PER_ARTIST = 50

# Bounded per item rather than on the list, for the reason `TermList` in `schemas.title`
# documents: an over-long variant would otherwise reach a String(300) column as a 500.
VariantList = list[Annotated[str, Field(max_length=ARTIST_TERM_MAX_LENGTH)]]

NO_CONTACT_MESSAGE = "Tagging an artist needs a way to reach them — an email address or a handle"


class ArtistHandleCreate(BaseModel):
    """One social handle, with the network it belongs to."""

    platform: str = Field(min_length=1, max_length=ARTIST_PLATFORM_MAX_LENGTH)
    handle: str = Field(min_length=1, max_length=ARTIST_TERM_MAX_LENGTH)


class TaggedArtistCreate(BaseModel):
    """The tagging form, field for field.

    `name_variants` and `handles` are the artist's identity set as the production house
    knows it. E01-S04 shows these back to the artist to correct — which is why they are
    captured here rather than left until the artist has an account.
    """

    artist_name: str = Field(min_length=1, max_length=ARTIST_NAME_MAX_LENGTH)
    contact_email: EmailStr | None = Field(
        default=None,
        description="The redeemable channel. Acceptance matches the redeemer's address to it.",
    )
    contact_handle: str | None = Field(
        default=None,
        max_length=ARTIST_TERM_MAX_LENGTH,
        description="Used when there is no email — the owner passes the link on by hand.",
    )
    name_variants: VariantList = Field(default_factory=list, max_length=MAX_VARIANTS_PER_ARTIST)
    handles: list[ArtistHandleCreate] = Field(
        default_factory=list, max_length=MAX_HANDLES_PER_ARTIST
    )

    @model_validator(mode="after")
    def require_a_contact_channel(self) -> "TaggedArtistCreate":
        """The story's third Given: there has to be somewhere to send the invitation.

        Emptiness is judged with `has_meaningful_content`, the same test the service
        applies when it cleans the handle — not `str.strip()`. The two have to agree: a
        handle of nothing but a zero-width space survives `strip()` but collapses to
        `None` on the way to the column, and the row would then fail
        `ck_title_membership_has_contact` at insert. That surfaces as an IntegrityError
        the tag path reports as "already tagged", which is the wrong error family, the
        wrong message, and confusing on a title nobody has ever been tagged on.
        """
        if self.contact_email is None and not _has_text(self.contact_handle):
            raise ValueError(NO_CONTACT_MESSAGE)
        return self

    @model_validator(mode="after")
    def normalize_contact_email(self) -> "TaggedArtistCreate":
        """Lowercased on the way in, so acceptance can compare it literally."""
        if self.contact_email is not None:
            object.__setattr__(self, "contact_email", self.contact_email.strip().lower())
        return self


def _has_text(value: str | None) -> bool:
    return value is not None and has_meaningful_content(value)


class ArtistTermRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    term_type: ArtistTermType
    value: str
    normalized_value: str
    platform: str | None


class ArtistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    terms: list[ArtistTermRead]


class MembershipScope(BaseModel):
    """What this membership will let its holder see, in the words the screen shows.

    Rendered on the tagging screen before the invitation goes out and on the Members
    screen afterwards. Derived from the role rather than stored, so the promise made to
    the owner and the access actually enforced cannot drift apart.
    """

    can_see_only_mentions_naming_subject: bool
    can_edit_title_setup: bool
    summary: str


class SharedOrganizationRead(BaseModel):
    """The agency a title is shared with, as the Members screen names it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str


class TitleMembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title_id: uuid.UUID
    role: TitleRole
    status: TitleMembershipStatus
    artist: ArtistRead | None
    # Set for an agency grant, null for a tagged artist. Exactly one of this and `artist`
    # is present, matching the membership's own subject.
    subject_organization: SharedOrganizationRead | None
    invited_email: str | None
    invited_handle: str | None
    scope: MembershipScope
    # Null for an agency grant — nothing was ever sent.
    last_sent_at: datetime | None
    accepted_at: datetime | None
    created_at: datetime


class TitleMembershipCreated(TitleMembershipRead):
    """Carries the raw acceptance token exactly once, on the response that mints it.

    Same seam and same reason as `InvitationCreated`: v1 has no mail transport, so the
    link has to reach the owner to pass on.
    """

    token: str


class TitleMembersView(BaseModel):
    """Everything the title's access panel renders."""

    memberships: list[TitleMembershipRead]


class AgencyShareCreate(BaseModel):
    """The sharing form. One organization, and the titles are picked explicitly.

    There is deliberately no "share all titles" flag and no default: the story requires
    the studio to name the titles, because the whole point of the grant is that the rest
    of the slate — including the unannounced part — stays invisible.
    """

    agency_organization_id: uuid.UUID


class AccessAuditEventRead(BaseModel):
    """One recorded change to who can see a title."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: AccessAuditAction
    role: TitleRole
    actor_user_id: uuid.UUID
    subject_organization_id: uuid.UUID | None
    subject_user_id: uuid.UUID | None
    subject_name: str
    created_at: datetime


class TitleInvitationToken(BaseModel):
    """The token alone, as the preview and the resend responses carry it."""

    token: str


class TitleInvitationPreview(BaseModel):
    """What the artist is shown before they commit (E01-S04).

    Carries the identity set the production house entered so the acceptance form can
    pre-fill it. Every field here is correctable — the point of showing it is that the
    artist is the only person who actually knows which spellings are theirs.
    """

    title_name: str
    organization_name: str
    artist_display_name: str
    invited_email: str | None
    name_variants: list[str]
    handles: list[ArtistHandleCreate]
    scope: MembershipScope
    # Stated as data rather than baked into the page, so the promise the API makes and
    # the sentence the artist reads are the same string.
    privacy_notice: str


class TitleInvitationAccept(BaseModel):
    """The artist's confirmed identity set, replacing what the production house guessed.

    `name_variants` and `handles` are the *whole* corrected set, not a delta — the form
    lets the artist remove a variant, and a merge-only payload has no way to say "this
    spelling is not me".
    """

    token: str
    name_variants: VariantList = Field(default_factory=list, max_length=MAX_VARIANTS_PER_ARTIST)
    handles: list[ArtistHandleCreate] = Field(
        default_factory=list, max_length=MAX_HANDLES_PER_ARTIST
    )

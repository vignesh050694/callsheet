"""The artist's side of a title invitation: previewing it, and accepting it (E01-S04).

Split from `TitleMembershipService` by actor rather than by table. That service is
everything the production house does to a membership — tagging, listing, untagging,
re-issuing the link. This one is everything the invited artist does, and the two have
opposite trust assumptions: the owner is acting inside their own organization, while the
accepter is a stranger holding a capability token and is trusted with nothing until the
token and their verified email agree.

The correction step is the point of the story, not decoration. The production house
guesses an actor's spellings from a cast sheet; the actor is the only person who knows
which of them are actually theirs. Whatever they confirm here replaces the guess.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PermissionDeniedError,
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from app.core.identity_terms import (
    clean_display_value,
    has_meaningful_content,
    joiner_folded,
    normalize_term,
)
from app.core.tokens import hash_invitation_token
from app.models.artist import (
    ARTIST_PLATFORM_MAX_LENGTH,
    ARTIST_TERM_MAX_LENGTH,
    Artist,
    ArtistIdentityTerm,
    ArtistTermType,
)
from app.models.title import Title
from app.models.title_membership import TitleMembership, TitleMembershipStatus
from app.models.user import User
from app.repositories.artist_repository import ArtistRepository
from app.repositories.membership_repository import MembershipRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.title_membership_repository import TitleMembershipRepository
from app.repositories.title_repository import TitleRepository
from app.schemas.title_membership import ArtistHandleCreate, TitleInvitationAccept
from app.services.identity_rules import ensure_fits

_logger = structlog.get_logger(__name__)

INVALID_TOKEN_MESSAGE = "This invitation link is not valid"
WRONG_RECIPIENT_MESSAGE = "This invitation was sent to a different email address"
UNVERIFIED_EMAIL_MESSAGE = "Verify your email address before accepting an invitation"
UNVERIFIABLE_INVITATION_MESSAGE = (
    "This invitation was sent to a social handle, which cannot be verified. Ask the "
    "production house to re-send it to your email address."
)
ALREADY_CLAIMED_MESSAGE = "This artist has already been linked to a different account"
NO_IDENTITY_MESSAGE = "Confirm at least one name variant or handle so your mentions can be matched"

PRIVACY_NOTICE = (
    "Your personal dashboard is yours. The production house that invited you can see this "
    "title's coverage, but not your dashboard, and not the mentions of you on anything else "
    "they have not tagged you on."
)


class TitleInvitationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._membership_repository = TitleMembershipRepository(session)
        # The organization memberships this account holds — how an agency manager reaches
        # the titles shared with their agency (E01-S05).
        self._organization_membership_repository = MembershipRepository(session)
        self._artist_repository = ArtistRepository(session)
        self._title_repository = TitleRepository(session)
        self._organization_repository = OrganizationRepository(session)

    async def preview_invitation(
        self, raw_token: str, caller: User
    ) -> tuple[TitleMembership, Title, str]:
        """Shows what is being offered, and the identity set the form pre-fills from.

        Read-only and idempotent: opening the link must not consume the invitation, so a
        prefetching mail client cannot accept on the artist's behalf.
        """
        membership = await self._require_redeemable(raw_token, caller)
        title = await self._require_title(membership.title_id)
        organization_name = await self._organization_name_for(title)
        return membership, title, organization_name

    async def accept_invitation(
        self, payload: TitleInvitationAccept, caller: User
    ) -> TitleMembership:
        """Claims the artist entity for this account and stores the corrected identity set."""
        membership = await self._require_redeemable(payload.token, caller)
        artist = membership.artist
        if artist is None:
            # Guaranteed by `ck_title_membership_artist_subject`, but the type is optional
            # because an agency grant (E01-S05) carries no artist.
            raise ValidationFailedError(INVALID_TOKEN_MESSAGE)

        self._ensure_claimable(artist, caller)
        confirmed_terms = self._build_confirmed_terms(payload)
        if not confirmed_terms:
            raise ValidationFailedError(NO_IDENTITY_MESSAGE)

        self._apply_confirmed_terms(artist, confirmed_terms)
        await self._claim_artist(artist, caller)

        membership.status = TitleMembershipStatus.ACTIVE
        membership.subject_user_id = caller.id
        membership.accepted_at = datetime.now(UTC)
        # Spent. A capability token that survives redemption can be replayed, and the
        # column is unique, so leaving it also blocks re-tagging this artist later.
        membership.token_hash = None

        membership_id = str(membership.id)
        artist_id = str(artist.id)
        caller_id = str(caller.id)
        try:
            await self._session.commit()
        except IntegrityError:
            # Nothing below may read an ORM object: `rollback()` expires them all, and a
            # lazy reload is what `lazy="raise"` exists to refuse.
            await self._session.rollback()
            _logger.warning("title_invitation.accept.conflict", membership_id=membership_id)
            raise ResourceConflictError(ALREADY_CLAIMED_MESSAGE) from None

        _logger.info(
            "title_invitation.accepted",
            membership_id=membership_id,
            artist_id=artist_id,
            user_id=caller_id,
            confirmed_term_count=len(confirmed_terms),
        )
        return await self._reload(membership.id)

    async def list_shared_titles(self, caller: User) -> list[Title]:
        """Every title this account can read through a grant rather than through ownership.

        Two routes in, and a person can hold both: an artist tagged directly, and an
        agency manager reaching titles through their organization (E01-S05). Merged and
        deduplicated, because the same title arriving by both paths is one entry in the
        client switcher, not two.

        Titles the caller's organization *owns* are deliberately absent — those come from
        `/organizations/{id}/titles`, which is an ownership question, not a sharing one.
        """
        titles = await self._membership_repository.list_active_titles_for_user(caller.id)
        organization_ids = [
            membership.organization_id
            for membership in await self._organization_membership_repository.list_for_user(
                caller.id
            )
        ]
        titles.extend(
            await self._membership_repository.list_active_titles_for_organizations(organization_ids)
        )

        seen: set[uuid.UUID] = set()
        merged: list[Title] = []
        for title in titles:
            if title.id in seen:
                continue
            seen.add(title.id)
            merged.append(title)
        # Re-sorted after the merge: each query was ordered on its own, and concatenating
        # two ordered lists does not produce an ordered list.
        merged.sort(key=lambda title: (title.release_date, title.id), reverse=True)
        return merged

    async def _require_redeemable(self, raw_token: str, caller: User) -> TitleMembership:
        """The token has to be live, and it has to be redeemed by the person it names."""
        membership = await self._membership_repository.get_pending_by_token_hash(
            hash_invitation_token(raw_token)
        )
        if membership is None:
            _logger.warning("title_invitation.invalid_token", user_id=str(caller.id))
            raise ResourceNotFoundError(INVALID_TOKEN_MESSAGE)

        if not caller.is_email_verified:
            _logger.warning("title_invitation.unverified_email", user_id=str(caller.id))
            raise PermissionDeniedError(UNVERIFIED_EMAIL_MESSAGE)

        if membership.invited_email is None:
            # A handle-only tag records who was meant to receive the link but proves
            # nothing about who is holding it. Redeeming on the token alone would let
            # anyone the link reached claim the artist entity, so v1 refuses and says
            # what to do instead. Verified handle ownership is out of scope for E01.
            _logger.warning(
                "title_invitation.unverifiable_channel", membership_id=str(membership.id)
            )
            raise PermissionDeniedError(UNVERIFIABLE_INVITATION_MESSAGE)

        if membership.invited_email != caller.email.strip().lower():
            # The token alone is not enough — a forwarded link must not admit whoever
            # opened it. Same rule organization invitations enforce (E01-S02).
            _logger.warning(
                "title_invitation.wrong_recipient",
                membership_id=str(membership.id),
                user_id=str(caller.id),
            )
            raise PermissionDeniedError(WRONG_RECIPIENT_MESSAGE)

        return membership

    @staticmethod
    def _ensure_claimable(artist: Artist, caller: User) -> None:
        """A fast, friendly refusal for the common case — not the guarantee.

        This reads a value that another transaction can change a moment later. It exists
        so an obviously-taken entity fails before the work of validating an identity set,
        and nothing depends on it being authoritative: `_claim_artist` re-decides against
        the database.
        """
        if artist.linked_user_id is not None and artist.linked_user_id != caller.id:
            _logger.warning(
                "title_invitation.already_claimed",
                artist_id=str(artist.id),
                user_id=str(caller.id),
            )
            raise ResourceConflictError(ALREADY_CLAIMED_MESSAGE)

    async def _claim_artist(self, artist: Artist, caller: User) -> None:
        """Takes the claim, or refuses — decided by the database, not by a prior read.

        The check above narrows the window but cannot close it. This is the arbiter: a
        conditional UPDATE that matches no rows when someone else already holds the
        entity. Losing it is a conflict, not a silent overwrite of whoever accepted first
        — which is the failure that matters most here, because the whole of identity
        verification in v1 rests on this one link (concept note risk #7).
        """
        artist_id = artist.id
        if await self._artist_repository.claim_for_user(artist_id, caller.id):
            return

        # Zero rows means the entity was already linked. That is legitimate when this
        # account is the holder — the same person accepting a tag on a second title —
        # and a conflict when it is anyone else.
        if await self._artist_repository.get_linked_to_user(artist_id, caller.id) is not None:
            return

        await self._session.rollback()
        _logger.warning(
            "title_invitation.claim_lost",
            artist_id=str(artist_id),
            user_id=str(caller.id),
        )
        raise ResourceConflictError(ALREADY_CLAIMED_MESSAGE)

    @staticmethod
    def _build_confirmed_terms(
        payload: TitleInvitationAccept,
    ) -> list[tuple[ArtistTermType, str, str, str | None]]:
        """The artist's corrected set, normalised and deduped, as (type, value, normal, platform).

        Built before anything is written so an invalid entry fails the whole acceptance
        rather than leaving the identity set half-replaced.
        """
        candidates: list[tuple[ArtistTermType, str, str | None]] = [
            (ArtistTermType.NAME_VARIANT, raw_variant, None)
            for raw_variant in payload.name_variants
        ]
        candidates.extend(
            (ArtistTermType.HANDLE, entry.handle, entry.platform) for entry in payload.handles
        )

        confirmed: list[tuple[ArtistTermType, str, str, str | None]] = []
        seen: set[tuple[ArtistTermType, str]] = set()
        for term_type, raw_value, platform in candidates:
            normalized_value = normalize_term(raw_value)
            if not has_meaningful_content(normalized_value):
                continue
            dedupe_key = (term_type, joiner_folded(normalized_value))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            value = clean_display_value(raw_value)
            # Bounded after NFKC, like every other value that reaches these columns.
            ensure_fits(value, ARTIST_TERM_MAX_LENGTH, "An artist identity term")
            ensure_fits(normalized_value, ARTIST_TERM_MAX_LENGTH, "An artist identity term")
            cleaned_platform = clean_display_value(platform) if platform is not None else None
            if cleaned_platform is not None:
                # Bounded post-NFKC like the value beside it. Pydantic caps the raw
                # string at 40, but `clean_display_value` normalises afterwards and NFKC
                # expands, so a 40-character platform built from compatibility characters
                # clears validation and then overflows `String(40)` — a Postgres
                # `DataError`, which is not an `IntegrityError` and so reaches the caller
                # as a 500 rather than a 422.
                ensure_fits(cleaned_platform, ARTIST_PLATFORM_MAX_LENGTH, "A handle platform")
            confirmed.append((term_type, value, normalized_value, cleaned_platform))
        return confirmed

    @staticmethod
    def _apply_confirmed_terms(
        artist: Artist,
        confirmed: list[tuple[ArtistTermType, str, str, str | None]],
    ) -> None:
        """Diffs the confirmed set against what is stored instead of replacing it.

        Replacing the collection outright does not work, for the reason
        `TitleService._apply_milestones` documents: SQLAlchemy emits the INSERTs before
        the DELETEs within one flush, so every variant the artist *kept* would collide
        with its own outgoing row on `uq_artist_term_normalized`. Diffing also keeps term
        ids stable across a correction, which matters once matches point at them.
        """
        desired = {
            (term_type, normalized_value): (value, platform)
            for term_type, value, normalized_value, platform in confirmed
        }
        existing = {(term.term_type, term.normalized_value): term for term in artist.terms}

        for key, term in existing.items():
            if key not in desired:
                # This is the removal half of "add, correct, or remove" — a spelling the
                # artist says is not theirs stops being matched on.
                artist.terms.remove(term)

        for key, (value, platform) in desired.items():
            kept = existing.get(key)
            if kept is None:
                term_type, normalized_value = key
                artist.terms.append(
                    ArtistIdentityTerm(
                        term_type=term_type,
                        value=value,
                        normalized_value=normalized_value,
                        platform=platform,
                    )
                )
            else:
                # Same term, retyped — take the artist's spelling and platform over the
                # production house's.
                kept.value = value
                kept.platform = platform

    async def _organization_name_for(self, title: Title) -> str:
        organization = await self._organization_repository.get_by_id(title.organization_id)
        if organization is None:
            raise ResourceNotFoundError(INVALID_TOKEN_MESSAGE)
        return organization.name

    async def _require_title(self, title_id: uuid.UUID) -> Title:
        title = await self._title_repository.get_by_id(title_id)
        if title is None:
            raise ResourceNotFoundError(INVALID_TOKEN_MESSAGE)
        return title

    async def _reload(self, membership_id: uuid.UUID) -> TitleMembership:
        """Re-reads with the artist and terms loaded — `lazy="raise"` refuses otherwise."""
        membership = await self._membership_repository.get_by_id(membership_id)
        if membership is None:
            raise ResourceNotFoundError(INVALID_TOKEN_MESSAGE)
        return membership


def prefilled_handles(artist: Artist) -> list[ArtistHandleCreate]:
    """The artist's stored handles, in the shape the acceptance form submits back."""
    return [
        ArtistHandleCreate(platform=term.platform or "", handle=term.value)
        for term in artist.terms
        if term.term_type.is_handle
    ]


def prefilled_name_variants(artist: Artist) -> list[str]:
    return [term.value for term in artist.terms if not term.term_type.is_handle]

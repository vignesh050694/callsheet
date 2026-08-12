"""Business logic for tagging artists on a title (E01-S03).

Owns the transaction boundary and every rule about who may be tagged and by whom. Knows
nothing about status codes — it raises domain errors and lets the API layer translate them.

The rule that matters here is that a tag names someone the title already knows about. The
identity set records who is attached to the film; tagging grants one of those people
access to the film's coverage. Letting an owner tag an arbitrary name would create an
artist entity nobody on the title has ever heard of, and — because a tagged artist sees
the mentions that name them — an entity whose slice of the coverage is empty by
construction.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
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
from app.core.tokens import generate_invitation_token, hash_invitation_token
from app.models.artist import (
    ARTIST_NAME_MAX_LENGTH,
    ARTIST_TERM_MAX_LENGTH,
    Artist,
    ArtistIdentityTerm,
    ArtistTermType,
)
from app.models.title import Title
from app.models.title_membership import (
    TITLE_MEMBERSHIP_HANDLE_MAX_LENGTH,
    TitleMembership,
    TitleMembershipStatus,
    TitleRole,
)
from app.models.user import User
from app.repositories.artist_repository import ArtistRepository
from app.repositories.membership_repository import MembershipRepository
from app.repositories.title_membership_repository import TitleMembershipRepository
from app.repositories.title_repository import TitleRepository
from app.schemas.title_membership import TaggedArtistCreate
from app.services.identity_rules import ensure_fits
from app.services.invitation_notifier import InvitationNotifier
from app.services.title_access import TitleAccessPolicy

_logger = structlog.get_logger(__name__)

TITLE_NOT_FOUND_MESSAGE = "Title {id} was not found"
MEMBERSHIP_NOT_FOUND_MESSAGE = "Membership {id} was not found"
NOT_AN_OWNER_MESSAGE = "Only an owner can tag an artist on this title"
EMPTY_ARTIST_NAME_MESSAGE = "An artist needs a name"
NOT_IN_CAST_MESSAGE = (
    "'{name}' is not on this title's cast list — add them to the title's cast, "
    "director, or music director credits first"
)
ALREADY_TAGGED_MESSAGE = "'{name}' is already tagged on this title"
NO_CONTACT_MESSAGE = "Tagging an artist needs a way to reach them — an email address or a handle"
NOT_PENDING_MESSAGE = "Membership {id} is {status}, not pending — there is nothing to resend"
NOT_UNTAGGABLE_MESSAGE = (
    "Membership {id} is {status}, not pending — end accepted access by revoking it, "
    "which is recorded in the access log"
)


class TitleMembershipService:
    def __init__(self, session: AsyncSession, notifier: InvitationNotifier) -> None:
        self._session = session
        self._notifier = notifier
        self._title_repository = TitleRepository(session)
        self._artist_repository = ArtistRepository(session)
        self._membership_repository = MembershipRepository(session)
        self._title_membership_repository = TitleMembershipRepository(session)
        self._access_policy = TitleAccessPolicy(session)

    async def tag_artist(
        self, title_id: uuid.UUID, payload: TaggedArtistCreate, caller: User
    ) -> tuple[TitleMembership, str]:
        """Tags a cast member and mints their pending membership, token returned once."""
        title = await self._require_title_owner(title_id, caller)

        display_name = clean_display_value(payload.artist_name)
        normalized_name = normalize_term(payload.artist_name)
        if not has_meaningful_content(normalized_name):
            raise ValidationFailedError(EMPTY_ARTIST_NAME_MESSAGE)
        ensure_fits(display_name, ARTIST_NAME_MAX_LENGTH, "An artist name")
        ensure_fits(normalized_name, ARTIST_NAME_MAX_LENGTH, "An artist name")
        self._ensure_named_on_title(title, normalized_name)

        artist = await self._resolve_artist(title.organization_id, display_name, normalized_name)
        self._merge_identity_terms(artist, display_name, normalized_name, payload)

        # Validated before the re-tag branch below, not after it. Both paths write the same
        # value to the same column, so a check that only guards one of them is not a check —
        # re-tagging a previously revoked artist used to skip both of these and store a
        # handle that fresh tagging correctly refuses.
        invited_handle = self._validated_contact_handle(payload)

        # A revoked tag still occupies `uq_title_membership_artist`, so re-tagging someone
        # whose access was ended (E01-S06) would otherwise be refused as a duplicate.
        # Reactivating keeps the artist's history on one row instead of splitting it.
        revoked = await self._title_membership_repository.get_for_title_and_artist(
            title_id, artist.id
        )
        if revoked is not None and revoked.status is TitleMembershipStatus.REVOKED:
            return await self._retag(revoked, title, display_name, invited_handle, payload, caller)

        raw_token = generate_invitation_token()
        membership = TitleMembership(
            title_id=title_id,
            artist_id=artist.id,
            role=TitleRole.TAGGED_ARTIST,
            status=TitleMembershipStatus.PENDING,
            invited_email=payload.contact_email,
            invited_handle=invited_handle,
            token_hash=hash_invitation_token(raw_token),
            invited_by_user_id=caller.id,
            last_sent_at=datetime.now(UTC),
        )
        await self._persist_tag(membership, display_name)

        await self._notifier.send_title_invitation(membership, title.name, display_name)
        _logger.info(
            "title_membership.artist_tagged",
            membership_id=str(membership.id),
            title_id=str(title_id),
            artist_id=str(artist.id),
            invited_by_user_id=str(caller.id),
        )
        return await self._reload(membership.id), raw_token

    async def list_memberships(self, title_id: uuid.UUID, caller: User) -> list[TitleMembership]:
        """Any member of the owning organization may see who has been let in.

        Through the shared policy, like every other access decision here. This method
        used to hand-roll the same check, which was a fourth copy of exactly the rule
        `TitleAccessPolicy` exists to hold — sitting in a service that already had the
        policy injected and used it everywhere else.
        """
        await self._access_policy.require_owning_organization(title_id, caller)
        return await self._title_membership_repository.list_for_title(title_id)

    async def resend_invitation(
        self, title_id: uuid.UUID, membership_id: uuid.UUID, caller: User
    ) -> tuple[TitleMembership, str]:
        """Re-issues the acceptance token, so a resent link supersedes the earlier one.

        This is the only way to recover a link. The raw token is returned exactly once,
        on the response that mints it, and is never stored — so an owner who tagged an
        artist and lost the link has to issue a new one rather than look the old one up.
        Same shape as `InvitationService.resend_invitation` (E01-S02).
        """
        title = await self._require_title_owner(title_id, caller)
        membership = await self._require_membership_on_title(title_id, membership_id)
        if not membership.is_pending:
            raise ValidationFailedError(
                NOT_PENDING_MESSAGE.format(id=membership_id, status=membership.status)
            )

        raw_token = generate_invitation_token()
        membership.token_hash = hash_invitation_token(raw_token)
        membership.last_sent_at = datetime.now(UTC)
        await self._session.commit()

        reloaded = await self._reload(membership_id)
        artist_name = reloaded.artist.display_name if reloaded.artist is not None else ""
        await self._notifier.send_title_invitation(reloaded, title.name, artist_name)
        _logger.info(
            "title_membership.invitation_resent",
            membership_id=str(membership_id),
            title_id=str(title_id),
            resent_by_user_id=str(caller.id),
        )
        return reloaded, raw_token

    async def untag_artist(
        self, title_id: uuid.UUID, membership_id: uuid.UUID, caller: User
    ) -> None:
        """Removes the tag and the access with it, in one action.

        Deleted rather than marked revoked: the story calls tagging reversible, and a
        removed tag has to be re-addable. A tombstone row would collide with
        `uq_title_membership_artist` the next time the same actor is tagged. Revocation
        of an *accepted* external grant is a different action with a different record
        (E01-S06) — this is the owner undoing their own tag.
        """
        title = await self._require_title_owner(title_id, caller)
        membership = await self._require_membership_on_title(title_id, membership_id)
        if not membership.is_pending:
            # Untagging is undoing an offer nobody took up, and it is deliberately not
            # audited — no access ever existed to record the end of. Ending access that
            # *was* accepted is revocation: it leaves a tombstone and an audit row, and
            # the two must not be interchangeable, or the access log would have a silent
            # bypass any API client could take (E01-S06).
            raise ValidationFailedError(
                NOT_UNTAGGABLE_MESSAGE.format(id=membership_id, status=membership.status)
            )

        artist_id = str(membership.artist_id)
        await self._title_membership_repository.delete(membership)
        await self._session.commit()

        _logger.info(
            "title_membership.artist_untagged",
            membership_id=str(membership_id),
            title_id=str(title.id),
            artist_id=artist_id,
            removed_by_user_id=str(caller.id),
        )

    @staticmethod
    def _validated_contact_handle(payload: TaggedArtistCreate) -> str | None:
        """The cleaned handle, or a 422 — the one place either tag path may get it from.

        The schema rejects a contactless tag, but this is the layer that decides what
        reaches the column, and cleaning can empty a handle the schema accepted. Checked
        here so an unreachable invitation is a 422 that names the problem rather than an
        IntegrityError surfacing through `_persist_tag` as "already tagged".

        The length bound is applied after normalisation, like every other value here that
        reaches a length-limited column. `clean_display_value` applies NFKC, which
        *expands*: 150 copies of the ligature "ﬃ" clear the schema's 300-character limit
        and become 450 on the way to a `String(300)`. Postgres answers that with a
        `DataError` — a sibling of `IntegrityError`, so the conflict handlers do not catch
        it either, and an otherwise valid tag becomes a 500. SQLite, which the tests run
        on, does not enforce VARCHAR limits at all, so nothing else would catch this
        before production.
        """
        invited_handle = _clean_optional(payload.contact_handle)
        if payload.contact_email is None and invited_handle is None:
            raise ValidationFailedError(NO_CONTACT_MESSAGE)
        if invited_handle is not None:
            ensure_fits(invited_handle, TITLE_MEMBERSHIP_HANDLE_MAX_LENGTH, "A contact handle")
        return invited_handle

    async def _retag(
        self,
        membership: TitleMembership,
        title: Title,
        display_name: str,
        invited_handle: str | None,
        payload: TaggedArtistCreate,
        caller: User,
    ) -> tuple[TitleMembership, str]:
        """Re-offers a tag whose access was revoked, on the row that already exists.

        A fresh token, because the old one was spent when the access ended, and back to
        `pending`: re-tagging is a new offer, not a silent restoration of access the
        artist has to accept again.
        """
        raw_token = generate_invitation_token()
        membership.status = TitleMembershipStatus.PENDING
        membership.revoked_at = None
        membership.accepted_at = None
        membership.subject_user_id = None
        membership.invited_email = payload.contact_email
        membership.invited_handle = invited_handle
        membership.token_hash = hash_invitation_token(raw_token)
        membership.invited_by_user_id = caller.id
        membership.last_sent_at = datetime.now(UTC)
        await self._session.commit()

        reloaded = await self._reload(membership.id)
        await self._notifier.send_title_invitation(reloaded, title.name, display_name)
        _logger.info(
            "title_membership.artist_retagged",
            membership_id=str(membership.id),
            title_id=str(title.id),
            invited_by_user_id=str(caller.id),
        )
        return reloaded, raw_token

    async def _persist_tag(self, membership: TitleMembership, display_name: str) -> None:
        """Commits the tag, letting the unique constraint arbitrate a double-submit."""
        try:
            await self._title_membership_repository.add(membership)
            await self._session.commit()
        except IntegrityError:
            # `rollback()` expires every ORM object, so nothing below may read one — the
            # same trap E01-S02's accept path documents. The name was read into a local
            # before the write for exactly this reason.
            await self._session.rollback()
            _logger.warning("title_membership.tag.conflict", artist_name=display_name)
            raise ResourceConflictError(ALREADY_TAGGED_MESSAGE.format(name=display_name)) from None

    async def _resolve_artist(
        self, organization_id: uuid.UUID, display_name: str, normalized_name: str
    ) -> Artist:
        """Reuses the organization's existing artist row, or creates it.

        Tagging the same actor on a second title must not fork their identity set — the
        corrections one artist makes (E01-S04) are meant to improve matching everywhere
        that organization tracks them.
        """
        existing = await self._artist_repository.get_by_normalized_name(
            organization_id, normalized_name
        )
        if existing is not None:
            return existing

        artist = Artist(
            organization_id=organization_id,
            display_name=display_name,
            normalized_name=normalized_name,
        )
        artist.terms = []
        return await self._artist_repository.add(artist)

    @staticmethod
    def _merge_identity_terms(
        artist: Artist,
        display_name: str,
        normalized_name: str,
        payload: TaggedArtistCreate,
    ) -> None:
        """Folds the form's variants and handles into the artist's set, without duplicates.

        Merged rather than replaced: a second tag of the same actor adds what this form
        knew and leaves everything an earlier tag established in place.

        The artist's own name goes in as a variant. Without it the set could consist
        entirely of handles, and a post naming the actor in plain text would not match.
        """
        existing_keys = {
            (term.term_type, joiner_folded(term.normalized_value)) for term in artist.terms
        }

        candidates: list[tuple[ArtistTermType, str, str | None]] = [
            (ArtistTermType.NAME_VARIANT, display_name, None)
        ]
        candidates.extend(
            (ArtistTermType.NAME_VARIANT, raw_variant, None)
            for raw_variant in payload.name_variants
        )
        candidates.extend(
            (ArtistTermType.HANDLE, entry.handle, entry.platform) for entry in payload.handles
        )

        for term_type, raw_value, platform in candidates:
            normalized_value = normalize_term(raw_value)
            # A variant of nothing but invisible characters is not a variant — the same
            # rejection the title identity set makes, for the same reason.
            if not has_meaningful_content(normalized_value):
                continue
            dedupe_key = (term_type, joiner_folded(normalized_value))
            if dedupe_key in existing_keys:
                continue
            existing_keys.add(dedupe_key)
            value = clean_display_value(raw_value)
            # Same NFKC-expansion trap the title terms carry — see `ensure_fits`.
            ensure_fits(value, ARTIST_TERM_MAX_LENGTH, "An artist identity term")
            ensure_fits(normalized_value, ARTIST_TERM_MAX_LENGTH, "An artist identity term")
            artist.terms.append(
                ArtistIdentityTerm(
                    term_type=term_type,
                    value=value,
                    normalized_value=normalized_value,
                    platform=clean_display_value(platform) if platform is not None else None,
                )
            )
        # Keeps the display name honest when the first tag typed it untidily and a later
        # one typed it properly; the normalized name, which the uniqueness key uses,
        # is unchanged by this.
        if normalized_name == artist.normalized_name:
            artist.display_name = display_name

    @staticmethod
    def _ensure_named_on_title(title: Title, normalized_name: str) -> None:
        """The tagged person has to be someone the title's identity set already names.

        Compared on the joiner-folded form, the same equivalence the exclusion guard uses:
        the owner types the name into the tag form independently of how they typed it into
        the cast list, and two spellings of one name have to be seen as one person.
        """
        people = {
            joiner_folded(term.normalized_value) for term in title.terms if term.term_type.is_anchor
        }
        if joiner_folded(normalized_name) not in people:
            _logger.warning(
                "title_membership.tag.not_in_cast",
                title_id=str(title.id),
                artist_name=normalized_name,
            )
            raise ValidationFailedError(NOT_IN_CAST_MESSAGE.format(name=normalized_name))

    async def _reload(self, membership_id: uuid.UUID) -> TitleMembership:
        """Re-reads with the artist and terms eagerly loaded, for the response shape.

        The write path leaves `TitleMembership.artist` unloaded and the relationship is
        `lazy="raise"`, so shaping the response off the just-committed object would raise
        rather than emit a query — which is the point of `lazy="raise"`.
        """
        membership = await self._title_membership_repository.get_by_id(membership_id)
        if membership is None:
            raise ResourceNotFoundError(MEMBERSHIP_NOT_FOUND_MESSAGE.format(id=membership_id))
        return membership

    async def _require_membership_on_title(
        self, title_id: uuid.UUID, membership_id: uuid.UUID
    ) -> TitleMembership:
        """A membership id from another title is a 404, not someone else's row to delete."""
        membership = await self._title_membership_repository.get_by_id(membership_id)
        if membership is None or membership.title_id != title_id:
            raise ResourceNotFoundError(MEMBERSHIP_NOT_FOUND_MESSAGE.format(id=membership_id))
        return membership

    async def _require_title_owner(self, title_id: uuid.UUID, caller: User) -> Title:
        """Owner-only, resolved through the one policy that decides title access.

        Kept as a named method because three call sites read better for it, but the rule
        itself lives in `TitleAccessPolicy` since E01-S05 — a viewer or an agency holding
        a read-only grant gets 403 because they can already see the title, and a stranger
        gets the same 404 a missing title gets.
        """
        access = await self._access_policy.require_administrable(
            title_id, caller, owner_message=NOT_AN_OWNER_MESSAGE
        )
        return access.title


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = clean_display_value(value)
    return cleaned if has_meaningful_content(cleaned) else None

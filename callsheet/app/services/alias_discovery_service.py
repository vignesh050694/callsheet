"""Discovering identity terms from a title's own corpus, and deciding on them (E02-S04).

Three acts, and they are deliberately not symmetrical:

* **Suggesting** is derived, never stored. What makes a candidate worth showing is how
  many posts carry it, and that changes with every poll — a stored suggestion list is
  wrong by the next cycle. It is re-mined on read.
* **Rejecting** is stored, because there is nowhere else for a "no" to live and without it
  the same seven hashtags come back after every poll.
* **Approving** writes a `TitleTerm`, which is the identity set itself remembering the
  "yes". The next cycle picks it up with no further wiring, because the query plan is
  built from the identity set rather than from anything this service holds.

Approving also re-matches the corpus already collected, and **that path cannot spend**:
it is a scan of stored mentions, the same architectural guarantee the reprocess service
gives (E03-S04). A studio approving `#DCFDFS` a week into a campaign sees the posts that
tag already brought in, without paying to fetch them a second time.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.alias_candidates import (
    AliasCandidate,
    MinedPost,
    folded_key,
    mine_alias_candidates,
)
from app.core.exceptions import (
    ResourceConflictError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from app.core.identity_terms import clean_display_value, has_meaningful_content, normalize_term
from app.core.post_matching import term_occurs_in
from app.db.constraints import describe_integrity_error
from app.models.mention import Mention
from app.models.mention_query_match import MatchSource, MentionQueryMatch
from app.models.title import TITLE_TERM_MAX_LENGTH, Title, TitleTerm
from app.models.title_alias_rejection import TitleAliasRejection
from app.models.user import User
from app.repositories.mention_query_match_repository import MentionQueryMatchRepository
from app.repositories.mention_repository import MentionRepository
from app.repositories.title_alias_rejection_repository import TitleAliasRejectionRepository
from app.schemas.alias_suggestion import (
    APPROVABLE_TERM_TYPES,
    NOT_APPROVABLE_MESSAGE,
    AliasApproval,
    AliasRejection,
)
from app.services.collection.query_plan import variant_key_for_term
from app.services.identity_rules import ensure_fits
from app.services.title_access import TitleAccessPolicy

_logger = structlog.get_logger(__name__)

NOT_AN_OWNER_MESSAGE = "Only an owner can change this title's identity set"
EMPTY_TERM_MESSAGE = "A suggestion has to contain at least one character that renders"
ALREADY_DECLARED_MESSAGE = "'{term}' is already part of this title's identity set"
IS_THE_TITLE_MESSAGE = "'{term}' is this title's own name — it is already collected on"
IS_EXCLUDED_MESSAGE = (
    "'{term}' is currently an exclusion term for this title. Remove the exclusion first — "
    "approving it as an alias while it also disqualifies posts would leave the title "
    "collecting and discarding the same conversation"
)
REJECTION_NOT_FOUND_MESSAGE = "That refused suggestion was not found on this title"

# How much of the corpus one suggestion read looks at, newest first. A cap rather than the
# whole corpus because this runs on a screen a studio opens repeatedly, and a six-month
# campaign is hundreds of thousands of posts. The number of posts actually read is
# reported alongside the counts, so a truncated ranking is visible rather than implied.
SUGGESTION_SCAN_LIMIT = 2_000

# How many suggestions are offered at once. The live run produced seven organic hashtags
# from twenty posts; a review wave produces far more, and a list nobody scrolls to the end
# of is a list where the good terms hide behind the noise.
SUGGESTION_LIMIT = 25

# The retroactive scan walks the *whole* corpus, in batches. Unlike the suggestion read it
# is not capped: "previously collected posts carrying it are re-matched" is the story's
# promise, and a cap would quietly break it on exactly the long campaigns where it matters.
REMATCH_BATCH_SIZE = 200


@dataclass(frozen=True, slots=True)
class AliasSuggestions:
    """The suggestion screen's whole payload, counts included.

    `scanned_mentions` and `corpus_size` are both here on purpose. They are equal until a
    campaign outgrows the scan cap, and the moment they diverge every count on the screen
    is a count over the recent window rather than the campaign. The screen says so.
    """

    title: Title
    candidates: list[AliasCandidate]
    samples: dict[uuid.UUID, Mention]
    rejections: list[TitleAliasRejection]
    scanned_mentions: int
    corpus_size: int


@dataclass(frozen=True, slots=True)
class AliasApprovalOutcome:
    """What approving did, in the terms the studio will ask about."""

    term: TitleTerm
    rematched_mentions: int
    scanned_mentions: int
    collection_calls: int = 0

    @property
    def has_spent_nothing(self) -> bool:
        """Always true, and asserted rather than assumed — see the module docstring."""
        return self.collection_calls == 0


class AliasDiscoveryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._access_policy = TitleAccessPolicy(session)
        self._mention_repository = MentionRepository(session)
        self._match_repository = MentionQueryMatchRepository(session)
        self._rejection_repository = TitleAliasRejectionRepository(session)

    async def list_suggestions(self, title_id: uuid.UUID, caller: User) -> AliasSuggestions:
        """Terms the corpus is using that this title does not claim, commonest first.

        Owner-gated rather than readable, because this is a setup control: everything on
        the screen is a decision about what the title collects, and an agency holding a
        read-only grant has nothing to do with it.
        """
        access = await self._access_policy.require_administrable(
            title_id, caller, owner_message=NOT_AN_OWNER_MESSAGE
        )
        title = access.title

        mentions = await self._mention_repository.list_for_title(
            title_id, limit=SUGGESTION_SCAN_LIMIT
        )
        rejected = await self._rejection_repository.folded_values_for_title(title_id)

        candidates = mine_alias_candidates(
            [
                MinedPost(id=mention.id, text=mention.text, hashtags=list(mention.hashtags or []))
                for mention in mentions
            ],
            declared_terms=self._declared_terms(title),
            rejected=rejected,
            limit=SUGGESTION_LIMIT,
        )

        by_id = {mention.id: mention for mention in mentions}
        _logger.info(
            "title.alias_suggestions.listed",
            title_id=str(title_id),
            candidates=len(candidates),
            scanned=len(mentions),
            user_id=str(caller.id),
        )
        return AliasSuggestions(
            title=title,
            candidates=candidates,
            samples={
                candidate.sample_mention_id: by_id[candidate.sample_mention_id]
                for candidate in candidates
                if candidate.sample_mention_id in by_id
            },
            rejections=await self._rejection_repository.list_for_title(title_id),
            scanned_mentions=len(mentions),
            corpus_size=await self._mention_repository.count_for_title(title_id),
        )

    async def approve(
        self, title_id: uuid.UUID, payload: AliasApproval, caller: User
    ) -> AliasApprovalOutcome:
        """Adds the term to the identity set and credits it against the stored corpus.

        One transaction covering both halves. Splitting them would leave a window where
        the term is in the set but nothing has been re-matched, and the screen that opens
        on that window reports a term earning nothing — which is the exact statement the
        studio is about to make a judgement on.
        """
        access = await self._access_policy.require_administrable(
            title_id, caller, owner_message=NOT_AN_OWNER_MESSAGE
        )
        title = access.title

        term = self._build_term(title, payload)
        title.terms.append(term)

        # An approval overrides an earlier refusal of the same word. Left in place, the
        # row would do no harm today — the miner never offers a declared term — but it
        # would silence the suggestion again the moment the term was removed from the set.
        stale_rejection = await self._rejection_repository.get_for_title_and_value(
            title_id, folded_key(payload.value)
        )
        if stale_rejection is not None:
            await self._rejection_repository.delete(stale_rejection)

        try:
            await self._session.flush()
        except IntegrityError as error:
            # The guards above already refuse a duplicate term with a 409 that names it.
            # This is the race: two owners approving the same suggestion at once. Nothing
            # here reads an ORM attribute — rollback expires them.
            message = describe_integrity_error(
                error, operation="title.alias.approve", title_id=str(title_id)
            )
            await self._session.rollback()
            raise ResourceConflictError(message) from None

        rematched, scanned = await self._rematch_corpus(title_id, term)
        await self._session.commit()

        _logger.info(
            "title.alias.approved",
            title_id=str(title_id),
            term=term.value,
            term_type=str(term.term_type),
            rematched=rematched,
            scanned=scanned,
            user_id=str(caller.id),
        )
        return AliasApprovalOutcome(
            term=term, rematched_mentions=rematched, scanned_mentions=scanned
        )

    async def reject(
        self, title_id: uuid.UUID, payload: AliasRejection, caller: User
    ) -> TitleAliasRejection:
        """Remembers a "no" so the same suggestion is never offered again.

        Rejecting a term that is already refused returns the existing row rather than a
        409. It is the same decision restated — usually a second tab, or a double-click on
        a list that has not refreshed — and answering an unchanged outcome with an error
        teaches people to distrust the screen.
        """
        await self._access_policy.require_administrable(
            title_id, caller, owner_message=NOT_AN_OWNER_MESSAGE
        )

        display_value, normalized_value, folded_value = self._clean(payload.value)
        existing = await self._rejection_repository.get_for_title_and_value(title_id, folded_value)
        if existing is not None:
            return existing

        rejection = TitleAliasRejection(
            title_id=title_id,
            kind=payload.kind,
            value=display_value,
            folded_value=folded_value,
            rejected_by_user_id=caller.id,
        )
        self._rejection_repository.add(rejection)
        try:
            await self._session.commit()
        except IntegrityError as error:
            # Two owners rejecting the same suggestion at once. Re-read rather than raise:
            # they agreed, and the row they agreed on is already there.
            await self._session.rollback()
            settled = await self._rejection_repository.get_for_title_and_value(
                title_id, folded_value
            )
            if settled is None:  # pragma: no cover — the unique constraint is the only race
                message = describe_integrity_error(
                    error, operation="title.alias.reject", title_id=str(title_id)
                )
                raise ResourceConflictError(message) from None
            return settled

        _logger.info(
            "title.alias.rejected",
            title_id=str(title_id),
            term=display_value,
            normalized=normalized_value,
            user_id=str(caller.id),
        )
        return rejection

    async def restore_rejected(
        self, title_id: uuid.UUID, rejection_id: uuid.UUID, caller: User
    ) -> None:
        """Forgets a "no", so the term can be suggested again if the corpus still uses it.

        The counterpart to `reject`, and not a convenience. "Never re-suggested" is a
        permanent decision made from one screenful of evidence early in a campaign, and a
        studio who rules out a tag that later turns out to be the film's own needs a way
        back that is not a support ticket.
        """
        await self._access_policy.require_administrable(
            title_id, caller, owner_message=NOT_AN_OWNER_MESSAGE
        )

        rejection = await self._rejection_repository.get_by_id(rejection_id)
        # Scoped to the title in the path, not just fetched by id: a rejection id from
        # another title would otherwise be deletable by anyone who owns any title.
        if rejection is None or rejection.title_id != title_id:
            raise ResourceNotFoundError(REJECTION_NOT_FOUND_MESSAGE)

        value = rejection.value
        await self._rejection_repository.delete(rejection)
        await self._session.commit()
        _logger.info(
            "title.alias.rejection_restored",
            title_id=str(title_id),
            term=value,
            user_id=str(caller.id),
        )

    def _build_term(self, title: Title, payload: AliasApproval) -> TitleTerm:
        """The approved term, validated against every rule the setup form enforces.

        Approving is a second door into the identity set, and a door that skipped these
        checks would be the way an over-long or invisible term got in — the setup form
        being careful is no protection if this is not.
        """
        display_value, normalized_value, folded_value = self._clean(payload.value)
        # The request schema refuses this first, so this is the backstop for a second
        # caller reaching the service directly — an exclusion approved as an alias would
        # leave the title collecting and discarding the same posts.
        if payload.term_type not in APPROVABLE_TERM_TYPES:  # pragma: no cover — schema-bound
            raise ValidationFailedError(NOT_APPROVABLE_MESSAGE)

        if folded_value == folded_key(title.name):
            raise ValidationFailedError(IS_THE_TITLE_MESSAGE.format(term=display_value))

        for existing in title.terms:
            if folded_key(existing.normalized_value) != folded_value:
                continue
            if existing.term_type.is_exclusion:
                raise ValidationFailedError(IS_EXCLUDED_MESSAGE.format(term=display_value))
            raise ResourceConflictError(ALREADY_DECLARED_MESSAGE.format(term=display_value))

        return TitleTerm(
            term_type=payload.term_type,
            value=display_value,
            normalized_value=normalized_value,
        )

    @staticmethod
    def _clean(raw_value: str) -> tuple[str, str, str]:
        """Display, stored, and comparison forms of a term, bounded after normalisation.

        `ensure_fits` is applied to both stored forms, for the reason it exists: NFKC
        expands, so a value that passed the request schema's `max_length` can still
        overflow a `String(300)` column — and SQLite does not enforce VARCHAR limits, so
        nothing catches it before Postgres does, as a 500.
        """
        display_value = clean_display_value(raw_value)
        normalized_value = normalize_term(raw_value)
        if not has_meaningful_content(normalized_value):
            raise ValidationFailedError(EMPTY_TERM_MESSAGE)
        ensure_fits(display_value, TITLE_TERM_MAX_LENGTH, "An identity term")
        ensure_fits(normalized_value, TITLE_TERM_MAX_LENGTH, "An identity term")
        return display_value, normalized_value, folded_key(raw_value)

    @staticmethod
    def _declared_terms(title: Title) -> list[str]:
        """Everything already settled for this title, so none of it is offered back.

        Exclusions are in here alongside the positive terms. They are settled in the
        opposite direction, but they are settled — offering a studio their own exclusion
        back as a discovery would be the product arguing with a decision it recorded.
        """
        return [title.name, *(term.value for term in title.terms)]

    async def _rematch_corpus(self, title_id: uuid.UUID, term: TitleTerm) -> tuple[int, int]:
        """Credits an approved term against posts already collected, spending nothing.

        Walked in keyset-paged batches on `(collected_at, id)` for the same reasons the
        reprocess walk uses that cursor (E03-S04): both components are immutable, and the
        leading one is ordered by arrival, so a mention inserted by a poll running
        alongside this lands ahead of the cursor rather than at a random position in it.

        Rows are written under `MatchSource.RETROACTIVE`. The term has not run as a query
        yet — the next cycle does that — so recording these as collection hits would
        credit it with fetching posts it never fetched.
        """
        variant_key = variant_key_for_term(term)
        matched_at = datetime.now(UTC)
        rematched = 0
        scanned = 0

        cursor_collected_at: datetime | None = None
        cursor_id: uuid.UUID | None = None
        while True:
            batch = await self._mention_repository.list_for_title_in_window(
                title_id,
                limit=REMATCH_BATCH_SIZE,
                after_collected_at=cursor_collected_at,
                after_id=cursor_id,
            )
            if not batch:
                break
            cursor_collected_at = batch[-1].collected_at
            cursor_id = batch[-1].id
            scanned += len(batch)

            hits = [
                mention
                for mention in batch
                if term_occurs_in(
                    [mention.text, " ".join(mention.hashtags or [])], term.normalized_value
                )
            ]
            if not hits:
                continue

            # The same term can be approved, removed, and approved again, and a poll can
            # have credited it in between. Asked for the batch in one query rather than
            # per mention, for the reason `existing_pairs` documents.
            already = await self._match_repository.existing_pairs(
                [mention.id for mention in hits], variant_key
            )
            new_matches = [
                MentionQueryMatch(
                    title_id=title_id,
                    mention_id=mention.id,
                    platform=mention.platform,
                    query_variant=variant_key,
                    first_matched_at=matched_at,
                    match_source=MatchSource.RETROACTIVE,
                )
                for mention in hits
                if mention.id not in already
            ]
            self._match_repository.add_all(new_matches)
            rematched += len(new_matches)

        return rematched, scanned

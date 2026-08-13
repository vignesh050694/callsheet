"""Disowning a colliding term, and everything it already dragged in (E02-S05).

The live run proved the need inside an anchored query: a post carrying `#DC #DareDevil`
matched on the studio's own short name and was about a superhero nobody in the production
had heard of. Three shared letters are enough to put another franchise's conversation into
a film's sentiment number.

Three properties shape this service, and each one is a decision the story makes explicitly:

* **The count comes before the confirmation.** A broad term can disown most of a title's
  corpus, and the difference between a good rule and a catastrophic one is invisible in the
  term itself — `#DC` looks exactly like `#DareDevil` on screen. So the impact is measured
  first, against the posts already collected, and the studio confirms a number rather than
  a string.
* **Nothing is deleted.** A mention is marked with the term that disowned it. The corpus
  was paid for, the judgement is reversible, and lifting the rule is a flag flip rather
  than another collection.
* **It applies retroactively and permanently.** Marking is done where the rule is made and
  again where the next cycle stores a post, so "removed from all counts and charts, historic
  mentions included" and "future collection stops matching them" are the same mechanism seen
  from two ends.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
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
from app.core.post_matching import term_occurs_in
from app.db.constraints import describe_integrity_error
from app.models.mention import Mention
from app.models.title import TITLE_TERM_MAX_LENGTH, Title, TitleTerm, TitleTermType
from app.models.user import User
from app.repositories.mention_repository import MentionRepository
from app.schemas.exclusion import ExclusionCreate
from app.services.identity_rules import ensure_fits
from app.services.title_access import TitleAccessPolicy

_logger = structlog.get_logger(__name__)

NOT_AN_OWNER_MESSAGE = "Only an owner can change which terms this title excludes"
EMPTY_TERM_MESSAGE = "An exclusion term has to contain at least one character that renders"
ALREADY_EXCLUDED_MESSAGE = "'{term}' is already excluded from this title"
SELF_EXCLUDING_TERM_MESSAGE = (
    "'{term}' is part of this title's own identity, so excluding it would disqualify the "
    "title's own posts"
)
EXCLUSION_NOT_FOUND_MESSAGE = "That exclusion term was not found on this title"

# How many stored posts one impact measurement or one sweep reads per batch. The walk is
# bounded in memory, not in reach: an exclusion that only removed the most recent thousand
# posts would be a rule the studio could not audit and did not ask for.
EXCLUSION_SWEEP_BATCH_SIZE = 200

# How many disowned posts the confirmation screen quotes back. A number alone is not
# reviewable — "this would remove 412 posts" is only actionable beside two of them.
IMPACT_SAMPLE_LIMIT = 3


@dataclass(frozen=True, slots=True)
class ExclusionImpact:
    """What a rule would do, measured before it exists."""

    value: str
    normalized_value: str
    would_remove: int
    counted_now: int
    samples: list[Mention]
    is_already_excluded: bool = False

    @property
    def removes_everything(self) -> bool:
        """A rule that empties the corpus is almost always a mis-click, and says so."""
        return self.counted_now > 0 and self.would_remove == self.counted_now


@dataclass(frozen=True, slots=True)
class ExclusionOutcome:
    term: TitleTerm
    removed_mentions: int


@dataclass(frozen=True, slots=True)
class ExclusionRemoval:
    value: str
    restored_mentions: int


class TitleExclusionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._access_policy = TitleAccessPolicy(session)
        self._mention_repository = MentionRepository(session)

    async def list_exclusions(self, title_id: uuid.UUID, caller: User) -> list[TitleTerm]:
        """This title's exclusion terms, in the identity set's canonical order."""
        access = await self._access_policy.require_administrable(
            title_id, caller, owner_message=NOT_AN_OWNER_MESSAGE
        )
        return sorted(
            (term for term in access.title.terms if term.term_type.is_exclusion),
            key=lambda term: term.normalized_value,
        )

    async def measure_impact(
        self, title_id: uuid.UUID, value: str, caller: User
    ) -> ExclusionImpact:
        """How many counted posts this rule would remove, and a few of them.

        Reads only. This is the screen the story requires before a confirmation exists,
        and it is the reason a studio can tell `#DareDevil` from `#DC` — one removes four
        posts and the other removes the film.
        """
        access = await self._access_policy.require_administrable(
            title_id, caller, owner_message=NOT_AN_OWNER_MESSAGE
        )
        display_value, normalized_value = self._clean(value)
        self._ensure_not_self_defeating(access.title, normalized_value, display_value)

        matches, samples = await self._scan_for_matches(title_id, normalized_value)
        return ExclusionImpact(
            value=display_value,
            normalized_value=normalized_value,
            would_remove=matches,
            counted_now=await self._mention_repository.count_for_title(title_id),
            samples=samples,
            is_already_excluded=self._existing_exclusion(access.title, normalized_value)
            is not None,
        )

    async def add_exclusion(
        self, title_id: uuid.UUID, payload: ExclusionCreate, caller: User
    ) -> ExclusionOutcome:
        """Stores the rule and applies it to everything already collected, in one go.

        One transaction on purpose. A rule that existed but had not been applied would
        leave the dashboard reporting a number the studio has just been told is wrong, and
        the window is exactly when they go and look.
        """
        access = await self._access_policy.require_administrable(
            title_id, caller, owner_message=NOT_AN_OWNER_MESSAGE
        )
        title = access.title
        display_value, normalized_value = self._clean(payload.value)
        self._ensure_not_self_defeating(title, normalized_value, display_value)

        if self._existing_exclusion(title, normalized_value) is not None:
            raise ResourceConflictError(ALREADY_EXCLUDED_MESSAGE.format(term=display_value))

        term = TitleTerm(
            term_type=TitleTermType.EXCLUSION,
            value=display_value,
            normalized_value=normalized_value,
        )
        title.terms.append(term)

        try:
            await self._session.flush()
        except IntegrityError as error:
            # Two owners excluding the same term at once. Nothing here reads an ORM
            # attribute — rollback expires them.
            message = describe_integrity_error(
                error, operation="title.exclusion.add", title_id=str(title_id)
            )
            await self._session.rollback()
            raise ResourceConflictError(message) from None

        removed = await self._apply_to_corpus(title_id, normalized_value)
        await self._session.commit()

        _logger.info(
            "title.exclusion.added",
            title_id=str(title_id),
            term=display_value,
            removed_mentions=removed,
            user_id=str(caller.id),
        )
        return ExclusionOutcome(term=term, removed_mentions=removed)

    async def remove_exclusion(
        self, title_id: uuid.UUID, term_id: uuid.UUID, caller: User
    ) -> ExclusionRemoval:
        """Lifts a rule and gives back the posts it removed — without collecting anything.

        Posts are re-checked against the *remaining* exclusions rather than simply
        restored. A post can carry two disowned franchises, and handing it back because
        one rule was lifted would quietly undo the other.
        """
        access = await self._access_policy.require_administrable(
            title_id, caller, owner_message=NOT_AN_OWNER_MESSAGE
        )
        title = access.title

        term = next(
            (
                candidate
                for candidate in title.terms
                if candidate.id == term_id and candidate.term_type.is_exclusion
            ),
            None,
        )
        if term is None:
            raise ResourceNotFoundError(EXCLUSION_NOT_FOUND_MESSAGE)

        display_value = term.value
        normalized_value = term.normalized_value
        remaining = [
            other.normalized_value
            for other in title.terms
            if other.term_type.is_exclusion and other.id != term_id
        ]

        title.terms.remove(term)
        restored = await self._restore_excluded_by(title_id, normalized_value, remaining)
        await self._session.commit()

        _logger.info(
            "title.exclusion.removed",
            title_id=str(title_id),
            term=display_value,
            restored_mentions=restored,
            user_id=str(caller.id),
        )
        return ExclusionRemoval(value=display_value, restored_mentions=restored)

    async def _scan_for_matches(
        self, title_id: uuid.UUID, normalized_value: str
    ) -> tuple[int, list[Mention]]:
        """Counts the counted posts this term appears in, keeping the first few.

        Text matching in Python rather than SQL, because the question is "does this term
        appear as a whole word in this post", and that is the same question collection and
        the preview already answer — `LIKE '%dc%'` would match `abcdcx` and every
        Devanagari word containing the same code points mid-cluster.
        """
        matches = 0
        samples: list[Mention] = []
        async for batch in self._walk_counted(title_id):
            for mention in batch:
                if not self._disqualifies(mention, normalized_value):
                    continue
                matches += 1
                if len(samples) < IMPACT_SAMPLE_LIMIT:
                    samples.append(mention)
        return matches, samples

    async def _apply_to_corpus(self, title_id: uuid.UUID, normalized_value: str) -> int:
        """Marks every counted post this term disqualifies. Reads stored rows, spends nothing."""
        excluded_at = datetime.now(UTC)
        marked = 0
        async for batch in self._walk_counted(title_id):
            for mention in batch:
                if not self._disqualifies(mention, normalized_value):
                    continue
                mention.excluded_by_term = normalized_value
                mention.excluded_at = excluded_at
                marked += 1
        return marked

    async def _restore_excluded_by(
        self, title_id: uuid.UUID, normalized_value: str, remaining: list[str]
    ) -> int:
        """Clears one rule's marks, re-applying whichever of the others still bite."""
        excluded = await self._mention_repository.list_excluded_by_term(title_id, normalized_value)
        restored = 0
        for mention in excluded:
            still_excluded = next(
                (term for term in remaining if self._disqualifies(mention, term)), None
            )
            if still_excluded is not None:
                mention.excluded_by_term = still_excluded
                continue
            mention.excluded_by_term = None
            mention.excluded_at = None
            restored += 1
        return restored

    async def _walk_counted(self, title_id: uuid.UUID) -> AsyncIterator[list[Mention]]:
        """The corpus that currently counts, in keyset-paged batches.

        `(collected_at, id)` for the reasons `MentionRepository.list_for_title_in_window`
        documents: both components are immutable, so nothing this walk writes can move a
        row across the cursor. That matters more here than in a reprocess — this walk
        *sets the very column it filters on*, so an OFFSET walk would renumber under
        itself and skip a post for every one it marked.
        """
        cursor_collected_at: datetime | None = None
        cursor_id: uuid.UUID | None = None
        while True:
            batch = await self._mention_repository.list_for_title_in_window(
                title_id,
                limit=EXCLUSION_SWEEP_BATCH_SIZE,
                after_collected_at=cursor_collected_at,
                after_id=cursor_id,
                include_excluded=False,
            )
            if not batch:
                return
            cursor_collected_at = batch[-1].collected_at
            cursor_id = batch[-1].id
            yield batch

    @staticmethod
    def _disqualifies(mention: Mention, normalized_value: str) -> bool:
        """Whether this term appears in the post, text and platform tags alike."""
        return term_occurs_in([mention.text, " ".join(mention.hashtags or [])], normalized_value)

    @staticmethod
    def _existing_exclusion(title: Title, normalized_value: str) -> TitleTerm | None:
        folded = joiner_folded(normalized_value)
        return next(
            (
                term
                for term in title.terms
                if term.term_type.is_exclusion and joiner_folded(term.normalized_value) == folded
            ),
            None,
        )

    @staticmethod
    def _clean(raw_value: str) -> tuple[str, str]:
        """Display and stored forms, bounded after normalisation.

        `ensure_fits` for the reason it exists: NFKC expands, so a value that passed the
        request schema's `max_length` can still overflow a `String(300)` column — and
        SQLite does not enforce VARCHAR limits, so it surfaces first on Postgres, as a 500.
        """
        display_value = clean_display_value(raw_value)
        normalized_value = normalize_term(raw_value)
        if not has_meaningful_content(normalized_value):
            raise ValidationFailedError(EMPTY_TERM_MESSAGE)
        ensure_fits(display_value, TITLE_TERM_MAX_LENGTH, "An exclusion term")
        ensure_fits(normalized_value, TITLE_TERM_MAX_LENGTH, "An exclusion term")
        return display_value, normalized_value

    @staticmethod
    def _ensure_not_self_defeating(title: Title, normalized_value: str, display: str) -> None:
        """An exclusion may not name the title itself or anything in its identity set.

        The same guard `TitleService` applies at creation, enforced again here because
        this is the *other* door into the exclusion set and the failure is silent: a title
        excluding its own name collects normally and counts nothing, for a reason no screen
        shows. Compared joiner-folded, the equivalence matching uses — the candidate came
        out of a post and carries that post's joiners, the declared term carries the
        studio's, and the guard has to see the two as one word.
        """
        folded = joiner_folded(normalized_value)
        positive = {joiner_folded(normalize_term(title.name))}
        positive.update(
            joiner_folded(term.normalized_value)
            for term in title.terms
            if not term.term_type.is_exclusion
        )
        if folded in positive:
            _logger.warning(
                "title.exclusion.self_excluding_term", title_id=str(title.id), term=display
            )
            raise ValidationFailedError(SELF_EXCLUDING_TERM_MESSAGE.format(term=display))

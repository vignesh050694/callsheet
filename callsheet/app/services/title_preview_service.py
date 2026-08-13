"""Business logic for the setup preview (E02-S03).

Shows the studio what their identity set would actually collect, before they commit to
it. The rule this service exists to serve is that a badly described film should be found
out in the first minute of setup, not in a junk dashboard a day later.

Three things are deliberately *not* here:

* **Persistence.** Nothing this service produces is written. The sample is discarded when
  the studio closes it; collection proper starts at E03-S01. That is why it holds no
  repository beyond the membership lookup its access check needs.
* **Analysis.** No sentiment, no account typing, no language detection — that pipeline is
  E04, and running none of it is honest, whereas guessing would put a number on screen
  that nothing stands behind.
* **Scoring.** No precision grade on the sample. Twenty posts a human can read is a better
  judge of "is this my film?" than a number derived from twenty posts, and the story
  rules a numeric grade out of scope.
"""

import time
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from app.core.identity_terms import clean_display_value, has_meaningful_content, normalize_term
from app.core.post_matching import find_matching_terms, suggest_exclusion_terms
from app.core.preview_query import build_anchored_query
from app.models.membership import Membership
from app.models.title import TITLE_NAME_MAX_LENGTH, TITLE_TERM_MAX_LENGTH
from app.models.user import User
from app.repositories.membership_repository import MembershipRepository
from app.schemas.title_preview import TitlePreviewRequest
from app.services.identity_rules import (
    ensure_fits,
    ensure_name_is_collectable,
    is_name_collectable,
)
from app.services.preview_search import (
    PREVIEW_PLATFORM,
    PREVIEW_POST_LIMIT,
    PreviewSearch,
    SamplePost,
)

_logger = structlog.get_logger(__name__)

ORGANIZATION_NOT_FOUND_MESSAGE = "Organization {id} was not found"
NOT_AN_OWNER_MESSAGE = "Only an owner can preview matches for this organization"
EMPTY_NAME_MESSAGE = "A title needs a name"

# Enough to spot what contaminated a post without turning the card into a tag cloud.
MAX_EXCLUSION_CANDIDATES_PER_POST = 8


@dataclass(frozen=True, slots=True)
class IdentityDraft:
    """The unsaved identity set, in the two forms the preview needs it in.

    `terms` pairs each display value with its normalised form, in the order they should be
    reported back — name first, because "it matched your title's name" is the first thing
    a reader wants to know.
    """

    name: str
    terms: list[tuple[str, str]] = field(default_factory=list)
    anchor_values: list[str] = field(default_factory=list)

    @property
    def has_anchor_term(self) -> bool:
        return bool(self.anchor_values)

    @property
    def normalized_values(self) -> set[str]:
        return {normalized for _, normalized in self.terms}


@dataclass(frozen=True, slots=True)
class PreviewedPost:
    """A sampled post plus the evidence for and against it belonging to this title."""

    post: SamplePost
    matched_terms: list[str]
    candidate_exclusion_terms: list[str]


@dataclass(frozen=True, slots=True)
class TitlePreview:
    platform: str
    query: str
    post_limit: int
    posts: list[PreviewedPost]


class TitlePreviewService:
    def __init__(self, session: AsyncSession, search: PreviewSearch) -> None:
        self._membership_repository = MembershipRepository(session)
        self._search = search

    async def preview(
        self,
        organization_id: uuid.UUID,
        payload: TitlePreviewRequest,
        caller: User,
    ) -> TitlePreview:
        """Runs one capped search for a draft identity set and explains every result."""
        await self._require_owner(organization_id, caller)

        draft = self._build_draft(payload)
        # The same rule the save enforces, enforced first. Previewing an identity set that
        # cannot be saved would show the studio a sample of namesakes and then refuse the
        # save for a reason the sample had already made obvious.
        ensure_name_is_collectable(draft.name, has_anchor_term=draft.has_anchor_term)

        # Anchored on the same terms as the rule just applied: a name that needed a cast or
        # crew term to be saved needs one to be searched. The preview has to ask the question
        # collection will ask, or the sample it shows is not a sample of what gets collected.
        query = build_anchored_query(
            draft.name,
            draft.anchor_values,
            name_is_self_sufficient=is_name_collectable(draft.name, has_anchor_term=False),
        )
        posts = await self._search_once(query, organization_id, caller)

        return TitlePreview(
            platform=PREVIEW_PLATFORM,
            query=query,
            post_limit=PREVIEW_POST_LIMIT,
            posts=[self._describe(post, draft) for post in posts],
        )

    async def _search_once(
        self,
        query: str,
        organization_id: uuid.UUID,
        caller: User,
    ) -> list[SamplePost]:
        """One call, deduped, and re-capped on the way out.

        The cap is applied here as well as passed down because the port cannot enforce
        what an adapter chooses to return. A provider that ignores `limit` would otherwise
        widen a sample the studio has not paid for, and — worse — make the preview
        unrepresentative of the single page collection will actually read.
        """
        started_at = time.perf_counter()
        found = await self._search.search_recent(query, limit=PREVIEW_POST_LIMIT)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 1)

        unique = self._deduplicate(found)
        capped = unique[:PREVIEW_POST_LIMIT]
        if len(unique) > PREVIEW_POST_LIMIT:
            _logger.warning(
                "title.preview.provider_over_cap",
                returned=len(unique),
                limit=PREVIEW_POST_LIMIT,
            )

        _logger.info(
            "title.preview.completed",
            organization_id=str(organization_id),
            user_id=str(caller.id),
            platform=PREVIEW_PLATFORM,
            post_count=len(capped),
            duration_ms=duration_ms,
        )
        return capped

    @staticmethod
    def _deduplicate(posts: list[SamplePost]) -> list[SamplePost]:
        """First occurrence wins, order preserved — a repeated id is one post, twice."""
        unique: list[SamplePost] = []
        seen: set[str] = set()
        for post in posts:
            if post.external_id in seen:
                continue
            seen.add(post.external_id)
            unique.append(post)
        return unique

    @staticmethod
    def _describe(post: SamplePost, draft: IdentityDraft) -> PreviewedPost:
        """Works out why this post matched, and what in it looks like contamination."""
        haystacks = (post.text, post.author_display_name, post.author_handle)
        return PreviewedPost(
            post=post,
            matched_terms=find_matching_terms(haystacks, draft.terms),
            candidate_exclusion_terms=suggest_exclusion_terms(
                post.text,
                draft.normalized_values,
                MAX_EXCLUSION_CANDIDATES_PER_POST,
            ),
        )

    @staticmethod
    def _build_draft(payload: TitlePreviewRequest) -> IdentityDraft:
        """Folds the form's fields into one ordered, deduped set of comparable terms."""
        name = clean_display_value(payload.name)
        if not has_meaningful_content(name):
            raise ValidationFailedError(EMPTY_NAME_MESSAGE)
        # The same bound the save applies, and for the same reason it is applied after
        # normalisation rather than on the raw request: NFKC expands, so 250 copies of the
        # ligature "ﬁ" clear Pydantic's limit and become 500 characters here. Checked
        # before the search runs, because the point of refusing is not to spend a paid
        # call on an identity set the save is going to reject anyway.
        ensure_fits(name, TITLE_NAME_MAX_LENGTH, "This title name")

        # `(values, anchors the query)` rather than a list of anchor fields tested with
        # `in`: two fields holding equal lists compare equal, so an alias would be read as
        # a cast member whenever the studio typed the same term into both.
        ordered_fields: tuple[tuple[list[str], bool], ...] = (
            (payload.aliases, False),
            (payload.hashtags, False),
            (payload.lead_cast, True),
            (payload.directors, True),
            (payload.music_directors, True),
        )

        terms: list[tuple[str, str]] = [(name, normalize_term(name))]
        seen = {normalize_term(name)}
        anchor_values: list[str] = []

        for raw_values, is_anchor_field in ordered_fields:
            for raw_value in raw_values:
                normalized_value = normalize_term(raw_value)
                if not has_meaningful_content(normalized_value) or normalized_value in seen:
                    continue
                seen.add(normalized_value)
                display_value = clean_display_value(raw_value)
                ensure_fits(display_value, TITLE_TERM_MAX_LENGTH, "An identity term")
                ensure_fits(normalized_value, TITLE_TERM_MAX_LENGTH, "An identity term")
                terms.append((display_value, normalized_value))
                if is_anchor_field:
                    anchor_values.append(display_value)

        return IdentityDraft(name=name, terms=terms, anchor_values=anchor_values)

    async def _require_owner(self, organization_id: uuid.UUID, caller: User) -> Membership:
        """Same shape as adding a title: a preview is part of setting one up.

        A non-member is told the organization does not exist rather than that they are not
        allowed — the preview names an unreleased film, and who is tracking what is not
        something a stranger should be able to probe.
        """
        membership = await self._membership_repository.get_for_user_and_organization(
            caller.id, organization_id
        )
        if membership is None:
            _logger.warning(
                "title.preview.not_a_member",
                organization_id=str(organization_id),
                user_id=str(caller.id),
            )
            raise ResourceNotFoundError(ORGANIZATION_NOT_FOUND_MESSAGE.format(id=organization_id))
        if not membership.role.can_administer_organization:
            _logger.warning(
                "title.preview.permission_denied",
                organization_id=str(organization_id),
                user_id=str(caller.id),
                role=str(membership.role),
            )
            raise PermissionDeniedError(NOT_AN_OWNER_MESSAGE)
        return membership

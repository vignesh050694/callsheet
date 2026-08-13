"""The mentions feed — the screen an exclusion is decided from (E02-S05).

Deliberately narrow. The full dashboard feed is E05's, with segmentation, language
detection and sentiment; none of that has run yet. What this delivers is the one thing
E02-S05 cannot exist without: a studio looking at the posts their identity set actually
pulled in, with the evidence of *why* each one is there, and a way to say "not my title".

Two pieces of evidence per post, and they are the same two the setup preview shows
(E02-S03), computed by the same functions:

* **the identity terms found in it** — why it was collected;
* **the hashtags it carries that the identity set does not claim** — one of which is what
  dragged it in, and is therefore the exclusion rule worth proposing.

Access follows what each role was already promised, and the two shared roles were promised
different things — collapsing them is how one of them gets lied to.

* **The owning organization** reads the feed, as it reads everything about its own title.
* **An agency manager** reads it too. E01-S05's scope line is "reads and exports this title
  only": the same view as the owner, narrowed to one title rather than narrowed in content.
  Refusing them here would be a 404 on a title they can demonstrably see, and a regression
  against a promise the sharing screen already prints.
* **A tagged artist** is refused, with a 403 that says why. Their promise is genuinely
  narrower — "sees only mentions of this title that also mention them" — and that filtered
  view needs the artist's own identity terms, which is E06's. Serving them this feed would
  hand them the studio's whole corpus; serving them a 404 would deny a title they can see.
  Saying "your view of this is limited and is not built yet" is the only one of the three
  that is true.
"""

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PermissionDeniedError
from app.core.identity_terms import normalize_term
from app.core.post_matching import find_matching_terms, suggest_exclusion_terms
from app.models.mention import Mention
from app.models.title import Title
from app.models.user import User
from app.repositories.mention_repository import MentionRepository
from app.services.title_access import TitleAccess, TitleAccessPolicy

_logger = structlog.get_logger(__name__)

ARTIST_SCOPED_FEED_MESSAGE = (
    "Your access to this title covers only the mentions that also name you. That filtered "
    "view is not available yet, so this feed is not shown to you rather than showing you "
    "more than you were granted."
)

# How many candidate exclusion terms are offered per post. A post carrying nine hashtags
# offers a menu nobody reads; the ones that dragged it in are near the front.
MAX_EXCLUSION_CANDIDATES_PER_POST = 5


@dataclass(frozen=True, slots=True)
class FeedMention:
    """One post, with the evidence needed to judge whether it belongs to this title."""

    mention: Mention
    matched_terms: list[str]
    candidate_exclusion_terms: list[str]


@dataclass(frozen=True, slots=True)
class MentionFeed:
    """A page of the feed, and the two totals that make the page legible.

    `counted_total` and `collected_total` differ by exactly what the title's exclusion
    rules removed. Both are shown, because a studio who has just disowned four hundred
    posts should be able to see that the corpus still holds them.
    """

    items: list[FeedMention]
    counted_total: int
    collected_total: int
    limit: int
    offset: int


class MentionFeedService:
    def __init__(self, session: AsyncSession) -> None:
        self._access_policy = TitleAccessPolicy(session)
        self._mention_repository = MentionRepository(session)

    async def list_mentions(
        self,
        title_id: uuid.UUID,
        caller: User,
        *,
        limit: int,
        offset: int,
        include_excluded: bool = False,
    ) -> MentionFeed:
        """Newest first. Excluded posts are out unless the caller asks to see them.

        `include_excluded` exists for one purpose: after confirming a rule, showing what it
        removed. A studio has to be able to check the rule did what the count promised, and
        an exclusion whose effect is invisible is one they cannot audit or trust.
        """
        access = await self._access_policy.require_readable(title_id, caller)
        self._ensure_feed_is_whole_for(access, title_id, caller)
        title = access.title

        mentions = await self._mention_repository.list_for_title(
            title_id, limit=limit, offset=offset, include_excluded=include_excluded
        )
        # The title's own name leads, because it is the one term every variant carries and
        # therefore the commonest reason a post is here. Left out, a post collected on the
        # name alone shows an empty "matched" list — which reads as "collected for no
        # reason" on the exact screen built for judging whether it belongs.
        identity_terms = [
            (title.name, normalize_term(title.name)),
            *(
                (term.value, term.normalized_value)
                for term in title.terms
                if not term.term_type.is_exclusion
            ),
        ]
        known = self._claimed_terms(title)

        _logger.info(
            "title.mentions.listed",
            title_id=str(title_id),
            returned=len(mentions),
            include_excluded=include_excluded,
            user_id=str(caller.id),
        )
        return MentionFeed(
            items=[self._to_feed_item(mention, identity_terms, known) for mention in mentions],
            counted_total=await self._mention_repository.count_for_title(title_id),
            collected_total=await self._mention_repository.count_for_title_including_excluded(
                title_id
            ),
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def _ensure_feed_is_whole_for(
        access: TitleAccess, title_id: uuid.UUID, caller: User
    ) -> None:
        """Refuses the one role whose promised view of this feed is not the whole of it.

        Read off the role rather than restated, so this cannot drift from the sentence the
        tagging screen shows the owner when they grant the access. 403 rather than 404
        because the caller can see the title — they accepted an invitation to it — and
        pretending it is missing is a lie they could disprove in one click.
        """
        membership = access.membership
        if membership is None or not membership.role.can_see_only_mentions_naming_subject:
            return

        _logger.warning(
            "title.mentions.scoped_view_unavailable",
            title_id=str(title_id),
            user_id=str(caller.id),
            role=str(membership.role),
        )
        raise PermissionDeniedError(ARTIST_SCOPED_FEED_MESSAGE)

    @staticmethod
    def _claimed_terms(title: Title) -> list[str]:
        """Every term already settled, so none is offered back as contamination.

        Exclusions are in here beside the positive terms: a term already excluded is not a
        candidate for excluding again, and offering it would let a studio create a
        duplicate rule from a screen that looks like it is proposing a new one.
        """
        return [normalize_term(title.name), *(term.normalized_value for term in title.terms)]

    @staticmethod
    def _to_feed_item(
        mention: Mention, identity_terms: list[tuple[str, str]], known: list[str]
    ) -> FeedMention:
        haystacks = [mention.text, " ".join(mention.hashtags or [])]
        return FeedMention(
            mention=mention,
            matched_terms=find_matching_terms(haystacks, identity_terms),
            candidate_exclusion_terms=suggest_exclusion_terms(
                " \n".join(haystacks), known, MAX_EXCLUSION_CANDIDATES_PER_POST
            ),
        )

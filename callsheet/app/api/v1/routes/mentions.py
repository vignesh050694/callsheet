"""Mentions feed and exclusion rules (E02-S05).

Routing only: validate the request shape, call one service method, shape the response.
Every rule about what may be excluded lives in `TitleExclusionService`.
"""

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, MentionFeedServiceDep, TitleExclusionServiceDep
from app.models.mention import Mention
from app.schemas.exclusion import (
    MAX_FEED_PAGE_SIZE,
    ExclusionCreate,
    ExclusionCreatedRead,
    ExclusionImpactRead,
    ExclusionRead,
    ExclusionRemovedRead,
    MentionFeedRead,
    MentionRead,
)
from app.schemas.title import TitleTermRead
from app.services.mention_feed_service import FeedMention, MentionFeed

router = APIRouter(tags=["mentions"])

DEFAULT_FEED_PAGE_SIZE = 25


def to_mention_read(
    mention: Mention,
    *,
    matched_terms: list[str] | None = None,
    candidate_exclusion_terms: list[str] | None = None,
) -> MentionRead:
    """One post as the API reports it.

    The two evidence lists default to empty rather than being required, because the impact
    samples are quoted to explain a *rule* rather than to be judged term by term — the
    studio is looking at what the rule would remove, and the terms that pulled each post in
    are the question they have already answered.
    """
    return MentionRead(
        id=mention.id,
        platform=str(mention.platform),
        author_handle=mention.author_handle,
        author_display_name=mention.author_display_name,
        text=mention.text,
        posted_at=mention.posted_at,
        permalink=mention.permalink,
        platform_reported_language=mention.platform_reported_language,
        hashtags=list(mention.hashtags or []),
        matched_terms=matched_terms or [],
        candidate_exclusion_terms=candidate_exclusion_terms or [],
        excluded_by_term=mention.excluded_by_term,
        excluded_at=mention.excluded_at,
    )


def _to_feed_item_read(item: FeedMention) -> MentionRead:
    return to_mention_read(
        item.mention,
        matched_terms=item.matched_terms,
        candidate_exclusion_terms=item.candidate_exclusion_terms,
    )


@router.get(
    "/titles/{title_id}/mentions",
    response_model=MentionFeedRead,
    summary="Posts collected for this title, with why each one matched",
)
async def list_title_mentions(
    title_id: uuid.UUID,
    feed_service: MentionFeedServiceDep,
    current_user: CurrentUser,
    limit: int = Query(default=DEFAULT_FEED_PAGE_SIZE, ge=1, le=MAX_FEED_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    include_excluded: bool = Query(
        default=False,
        description=(
            "Show posts an exclusion rule has disowned. Off by default — they are not "
            "part of this title. On, so a studio can check a rule did what it promised."
        ),
    ),
) -> MentionFeedRead:
    feed: MentionFeed = await feed_service.list_mentions(
        title_id,
        current_user,
        limit=limit,
        offset=offset,
        include_excluded=include_excluded,
    )
    return MentionFeedRead(
        items=[_to_feed_item_read(item) for item in feed.items],
        counted_total=feed.counted_total,
        collected_total=feed.collected_total,
        limit=feed.limit,
        offset=feed.offset,
    )


@router.get(
    "/titles/{title_id}/exclusions",
    response_model=list[ExclusionRead],
    summary="Terms that disqualify a post from this title",
)
async def list_title_exclusions(
    title_id: uuid.UUID,
    exclusion_service: TitleExclusionServiceDep,
    current_user: CurrentUser,
) -> list[ExclusionRead]:
    terms = await exclusion_service.list_exclusions(title_id, current_user)
    return [
        ExclusionRead(id=term.id, value=term.value, normalized_value=term.normalized_value)
        for term in terms
    ]


@router.post(
    "/titles/{title_id}/exclusions/impact",
    response_model=ExclusionImpactRead,
    summary="How many already-collected posts this rule would remove",
)
async def measure_exclusion_impact(
    title_id: uuid.UUID,
    payload: ExclusionCreate,
    exclusion_service: TitleExclusionServiceDep,
    current_user: CurrentUser,
) -> ExclusionImpactRead:
    """A read that takes a body, so POST rather than GET.

    The term is arbitrary user text — hashes, Tamil script, emoji — and putting it in a
    query string means every client has to get the encoding right to ask a question. It
    writes nothing: the rule does not exist until `POST /exclusions` creates it.
    """
    impact = await exclusion_service.measure_impact(title_id, payload.value, current_user)
    return ExclusionImpactRead(
        value=impact.value,
        normalized_value=impact.normalized_value,
        would_remove=impact.would_remove,
        counted_now=impact.counted_now,
        removes_everything=impact.removes_everything,
        is_already_excluded=impact.is_already_excluded,
        samples=[to_mention_read(mention) for mention in impact.samples],
    )


@router.post(
    "/titles/{title_id}/exclusions",
    response_model=ExclusionCreatedRead,
    status_code=status.HTTP_201_CREATED,
    summary="Exclude a term, removing what it already matched from every count",
)
async def create_title_exclusion(
    title_id: uuid.UUID,
    payload: ExclusionCreate,
    exclusion_service: TitleExclusionServiceDep,
    current_user: CurrentUser,
) -> ExclusionCreatedRead:
    outcome = await exclusion_service.add_exclusion(title_id, payload, current_user)
    return ExclusionCreatedRead(
        term=TitleTermRead.model_validate(outcome.term),
        removed_mentions=outcome.removed_mentions,
    )


@router.delete(
    "/titles/{title_id}/exclusions/{term_id}",
    response_model=ExclusionRemovedRead,
    summary="Lift an exclusion, giving back the posts it removed",
)
async def delete_title_exclusion(
    title_id: uuid.UUID,
    term_id: uuid.UUID,
    exclusion_service: TitleExclusionServiceDep,
    current_user: CurrentUser,
) -> ExclusionRemovedRead:
    """200 with a body rather than 204: how many posts came back is the point of the action.

    Nothing is re-collected. The posts were never deleted — the rule marked them, and
    lifting it unmarks whatever no *other* rule still disowns.
    """
    removal = await exclusion_service.remove_exclusion(title_id, term_id, current_user)
    return ExclusionRemovedRead(value=removal.value, restored_mentions=removal.restored_mentions)

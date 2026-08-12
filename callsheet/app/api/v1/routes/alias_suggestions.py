"""Alias discovery routes — reviewing what the audience calls this title (E02-S04).

Routing only: validate the request shape, call one service method, shape the response.
Every rule about what may be approved lives in `AliasDiscoveryService`.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import AliasDiscoveryServiceDep, CurrentUser
from app.schemas.alias_suggestion import (
    AliasApproval,
    AliasApprovalRead,
    AliasCandidateRead,
    AliasRejection,
    AliasRejectionRead,
    AliasSamplePostRead,
    AliasSuggestionsRead,
)
from app.schemas.title import TitleTermRead
from app.services.alias_discovery_service import AliasSuggestions

router = APIRouter(tags=["alias-suggestions"])


def to_suggestions_read(suggestions: AliasSuggestions) -> AliasSuggestionsRead:
    """Joins each candidate to the post it was sampled from.

    The sample is optional in the response rather than guaranteed, because the two are
    read at slightly different moments: a mention can be deleted between mining and
    shaping. A candidate with a count and no quote is still worth showing — a candidate
    the endpoint refused to return because its quote vanished is not.
    """
    return AliasSuggestionsRead(
        candidates=[
            AliasCandidateRead(
                kind=candidate.kind,
                value=candidate.value,
                normalized_value=candidate.normalized_value,
                mention_count=candidate.mention_count,
                resembles=candidate.resembles,
                sample=(
                    AliasSamplePostRead.model_validate(sample, from_attributes=True)
                    if (sample := suggestions.samples.get(candidate.sample_mention_id))
                    else None
                ),
            )
            for candidate in suggestions.candidates
        ],
        rejections=[
            AliasRejectionRead.model_validate(rejection) for rejection in suggestions.rejections
        ],
        scanned_mentions=suggestions.scanned_mentions,
        corpus_size=suggestions.corpus_size,
    )


@router.get(
    "/titles/{title_id}/alias-suggestions",
    response_model=AliasSuggestionsRead,
    summary="Hashtags and name variants the corpus uses that this title does not claim",
)
async def list_alias_suggestions(
    title_id: uuid.UUID,
    alias_service: AliasDiscoveryServiceDep,
    current_user: CurrentUser,
) -> AliasSuggestionsRead:
    return to_suggestions_read(await alias_service.list_suggestions(title_id, current_user))


@router.post(
    "/titles/{title_id}/alias-suggestions/approvals",
    response_model=AliasApprovalRead,
    status_code=status.HTTP_201_CREATED,
    summary="Approve a discovered term into this title's identity set",
)
async def approve_alias_suggestion(
    title_id: uuid.UUID,
    payload: AliasApproval,
    alias_service: AliasDiscoveryServiceDep,
    current_user: CurrentUser,
) -> AliasApprovalRead:
    """201 rather than 200: this creates an identity term, and the term is the resource.

    The response carries what the approval was worth against the corpus already collected,
    because that is the number the studio approved it to find out.
    """
    outcome = await alias_service.approve(title_id, payload, current_user)
    return AliasApprovalRead(
        term=TitleTermRead.model_validate(outcome.term),
        rematched_mentions=outcome.rematched_mentions,
        scanned_mentions=outcome.scanned_mentions,
        collection_calls=outcome.collection_calls,
    )


@router.post(
    "/titles/{title_id}/alias-suggestions/rejections",
    response_model=AliasRejectionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Refuse a discovered term, so it is never suggested for this title again",
)
async def reject_alias_suggestion(
    title_id: uuid.UUID,
    payload: AliasRejection,
    alias_service: AliasDiscoveryServiceDep,
    current_user: CurrentUser,
) -> AliasRejectionRead:
    rejection = await alias_service.reject(title_id, payload, current_user)
    return AliasRejectionRead.model_validate(rejection)


@router.delete(
    "/titles/{title_id}/alias-suggestions/rejections/{rejection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Forget a refusal, letting the term be suggested again",
)
async def restore_rejected_alias_suggestion(
    title_id: uuid.UUID,
    rejection_id: uuid.UUID,
    alias_service: AliasDiscoveryServiceDep,
    current_user: CurrentUser,
) -> None:
    await alias_service.restore_rejected(title_id, rejection_id, current_user)

"""Historical backfill routes (E03-S03).

Routing only. Three endpoints, and the order they exist in is the order the screen uses
them: quote a range, confirm it, then watch what it managed to reach.

The quote is a POST rather than a GET despite writing nothing, because the range is a body
the UI already has and a GET would mean serialising two instants into a query string on
every keystroke. It is spelled `/estimate` so nothing about the path suggests it spends.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CollectionBackfillServiceDep, CurrentUser
from app.models.collection_backfill import CollectionBackfill
from app.schemas.backfill import (
    BackfillEstimateRead,
    BackfillRangeRequest,
    BackfillRead,
    PlatformBackfillEstimateRead,
)
from app.schemas.common import Page, PageParams
from app.services.collection_backfill_service import BackfillQuote

router = APIRouter(tags=["backfill"])


def _to_estimate_read(quote: BackfillQuote) -> BackfillEstimateRead:
    return BackfillEstimateRead(
        title_id=quote.title_id,
        requested_from=quote.requested_from,
        requested_until=quote.requested_until,
        variants=quote.estimate.variants,
        pages_per_query=quote.estimate.pages_per_query,
        page_size=quote.estimate.page_size,
        max_calls=quote.estimate.max_calls,
        max_cost_usd=quote.estimate.max_cost_usd,
        platforms=[
            PlatformBackfillEstimateRead(
                platform=platform.platform,
                endpoint_key=platform.endpoint_key,
                price_model=platform.price_model,
                calls=platform.calls,
                max_cost_usd=platform.max_cost_usd,
                unavailable_reason=platform.unavailable_reason,
            )
            for platform in quote.estimate.platforms
        ],
    )


def _to_backfill_read(backfill: CollectionBackfill) -> BackfillRead:
    return BackfillRead(
        id=backfill.id,
        title_id=backfill.title_id,
        status=backfill.status,
        requested_from=backfill.requested_from,
        requested_until=backfill.requested_until,
        page_cap=backfill.page_cap,
        estimated_calls=backfill.estimated_calls,
        estimated_max_cost_usd=backfill.estimated_max_cost_usd,
        pages_fetched=backfill.pages_fetched,
        unsegmented_mentions_stored=backfill.mentions_stored,
        mentions_already_known=backfill.mentions_already_known,
        unreadable=backfill.unreadable,
        charged_cost_usd=backfill.charged_cost_usd,
        earliest_posted_at=backfill.earliest_posted_at,
        is_depth_limited=backfill.is_depth_limited,
        has_reached_page_cap=backfill.has_reached_page_cap,
        started_at=backfill.started_at,
        finished_at=backfill.finished_at,
        failure_reason=backfill.failure_reason,
        created_at=backfill.created_at,
    )


@router.post(
    "/titles/{title_id}/backfills/estimate",
    response_model=BackfillEstimateRead,
    summary="What backfilling this range would cost, before anything is spent",
)
async def estimate_backfill_range(
    title_id: uuid.UUID,
    payload: BackfillRangeRequest,
    backfill_service: CollectionBackfillServiceDep,
    current_user: CurrentUser,
) -> BackfillEstimateRead:
    quote = await backfill_service.quote(
        title_id,
        current_user,
        requested_from=payload.requested_from,
        requested_until=payload.requested_until,
    )
    return _to_estimate_read(quote)


@router.post(
    "/titles/{title_id}/backfills",
    response_model=BackfillRead,
    status_code=status.HTTP_201_CREATED,
    summary="Collect this title's conversation from a past date range",
)
async def request_backfill(
    title_id: uuid.UUID,
    payload: BackfillRangeRequest,
    backfill_service: CollectionBackfillServiceDep,
    current_user: CurrentUser,
) -> BackfillRead:
    backfill = await backfill_service.request_backfill(
        title_id,
        current_user,
        requested_from=payload.requested_from,
        requested_until=payload.requested_until,
    )
    return _to_backfill_read(backfill)


@router.get(
    "/titles/{title_id}/backfills",
    response_model=Page[BackfillRead],
    summary="This title's backfill requests and how deep each one reached",
)
async def list_backfills(
    title_id: uuid.UUID,
    backfill_service: CollectionBackfillServiceDep,
    current_user: CurrentUser,
    page_params: Annotated[PageParams, Depends()],
) -> Page[BackfillRead]:
    backfills, total = await backfill_service.list_for_title(
        title_id, current_user, limit=page_params.limit, offset=page_params.offset
    )
    return Page(
        items=[_to_backfill_read(backfill) for backfill in backfills],
        total=total,
        limit=page_params.limit,
        offset=page_params.offset,
    )

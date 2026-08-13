"""Collection status routes (E03-S01).

Routing only. There is no route that *starts* collection — that is the story's point.
Collection begins because a title exists, not because somebody asked for it, so the only
thing a client needs from this layer is whether it is running.
"""

import uuid

from fastapi import APIRouter

from app.api.deps import CollectionStatusServiceDep, CurrentUser
from app.schemas.collection import PlatformHealthRead, TitleCollectionStatusRead
from app.services.collection_status_service import CollectionStatus

router = APIRouter(tags=["collection"])


def _to_status_read(status: CollectionStatus) -> TitleCollectionStatusRead:
    return TitleCollectionStatusRead(
        title_id=status.title_id,
        unsegmented_mention_count=status.mention_count,
        finished_run_count=status.finished_run_count,
        last_finished_at=status.last_finished_at,
        last_run_status=status.last_run_status,
        last_run_failure_reason=status.last_run_failure_reason,
        next_run_at=status.next_run_at,
        polls_per_day=status.polls_per_day,
        cadence_phase=status.cadence_phase,
        is_volume_escalated=status.is_volume_escalated,
        latest_mention_posted_at=status.latest_mention_posted_at,
        is_awaiting_first_results=status.is_awaiting_first_results,
        is_stalled=status.is_stalled,
        platforms=[
            PlatformHealthRead(
                platform=health.platform,
                state=health.state,
                last_successful_at=health.last_successful_at,
                last_failure_reason=health.last_failure_reason,
                consecutive_failures=health.consecutive_failures,
            )
            for health in status.platforms
        ],
        data_as_of=status.data_as_of,
    )


@router.get(
    "/titles/{title_id}/collection",
    response_model=TitleCollectionStatusRead,
    summary="Whether this title is collecting, and when it last did",
)
async def read_title_collection_status(
    title_id: uuid.UUID,
    collection_status_service: CollectionStatusServiceDep,
    current_user: CurrentUser,
) -> TitleCollectionStatusRead:
    status = await collection_status_service.status_for_title(title_id, current_user)
    return _to_status_read(status)

"""Title preview routes (E02-S03).

Routing only. The cap, the query, and the access check all live in `TitlePreviewService`.

`POST` for a read-only action, deliberately: the request body is the whole unsaved
identity set, which does not belong in a URL, and the call spends real money upstream, so
it must never be something a browser or proxy can replay from a cache.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, TitlePreviewServiceDep
from app.schemas.title_preview import PreviewPostRead, TitlePreviewRead, TitlePreviewRequest
from app.services.title_preview_service import PreviewedPost, TitlePreview

router = APIRouter(tags=["titles"])


def _to_preview_post_read(previewed: PreviewedPost) -> PreviewPostRead:
    post = previewed.post
    return PreviewPostRead(
        id=post.external_id,
        author_handle=post.author_handle,
        author_display_name=post.author_display_name,
        text=post.text,
        posted_at=post.posted_at,
        permalink=post.permalink,
        platform_reported_language=post.platform_reported_language,
        matched_terms=previewed.matched_terms,
        candidate_exclusion_terms=previewed.candidate_exclusion_terms,
    )


def _to_preview_read(preview: TitlePreview) -> TitlePreviewRead:
    return TitlePreviewRead(
        platform=preview.platform,
        query=preview.query,
        post_limit=preview.post_limit,
        posts=[_to_preview_post_read(previewed) for previewed in preview.posts],
    )


@router.post(
    "/organizations/{organization_id}/title-previews",
    response_model=TitlePreviewRead,
    status_code=status.HTTP_200_OK,
    summary="Sample what a draft identity set would collect",
)
async def preview_title_matches(
    organization_id: uuid.UUID,
    payload: TitlePreviewRequest,
    preview_service: TitlePreviewServiceDep,
    current_user: CurrentUser,
) -> TitlePreviewRead:
    preview = await preview_service.preview(organization_id, payload, current_user)
    return _to_preview_read(preview)

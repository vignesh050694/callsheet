"""The artist's side of a title invitation (E01-S04).

Routing only: validate the request shape, call one service method, shape the response.
Every rule about who may redeem what lives in `TitleInvitationService`.

Both endpoints take the token in the request body rather than the path or query string.
A capability token in a URL ends up in access logs, browser history, and referrer
headers; in a body it does not. The organization-invitation accept route (E01-S02) takes
it the same way, for the same reason.
"""

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, TitleInvitationServiceDep
from app.api.v1.routes.title_memberships import scope_for, to_membership_read
from app.api.v1.routes.titles import to_title_read
from app.schemas.title import TitleRead
from app.schemas.title_membership import (
    TitleInvitationAccept,
    TitleInvitationPreview,
    TitleInvitationToken,
    TitleMembershipRead,
)
from app.services.title_invitation_service import (
    PRIVACY_NOTICE,
    prefilled_handles,
    prefilled_name_variants,
)

router = APIRouter(tags=["title-invitations"])


@router.post(
    "/titles/invitations/preview",
    response_model=TitleInvitationPreview,
    summary="What this invitation offers, and the identity set to correct",
)
async def preview_title_invitation(
    payload: TitleInvitationToken,
    invitation_service: TitleInvitationServiceDep,
    current_user: CurrentUser,
) -> TitleInvitationPreview:
    """POST rather than GET because the token travels in the body — see the module note.

    It is still read-only: previewing does not consume the invitation.
    """
    membership, title, organization_name = await invitation_service.preview_invitation(
        payload.token, current_user
    )
    artist = membership.artist
    return TitleInvitationPreview(
        title_name=title.name,
        organization_name=organization_name,
        artist_display_name=artist.display_name if artist is not None else "",
        invited_email=membership.invited_email,
        name_variants=prefilled_name_variants(artist) if artist is not None else [],
        handles=prefilled_handles(artist) if artist is not None else [],
        scope=scope_for(membership),
        privacy_notice=PRIVACY_NOTICE,
    )


@router.post(
    "/titles/invitations/accept",
    response_model=TitleMembershipRead,
    status_code=status.HTTP_200_OK,
    summary="Accept a title invitation and confirm the identity set",
)
async def accept_title_invitation(
    payload: TitleInvitationAccept,
    invitation_service: TitleInvitationServiceDep,
    current_user: CurrentUser,
) -> TitleMembershipRead:
    membership = await invitation_service.accept_invitation(payload, current_user)
    return to_membership_read(membership)


@router.get(
    "/me/titles",
    response_model=list[TitleRead],
    summary="Titles shared with me through a title membership",
)
async def list_shared_titles(
    invitation_service: TitleInvitationServiceDep,
    current_user: CurrentUser,
) -> list[TitleRead]:
    """The artist's read-only list. Titles their own organization owns are not here —
    those arrive through `/organizations/{id}/titles`, which is an ownership question,
    not a sharing one."""
    titles = await invitation_service.list_shared_titles(current_user)
    return [to_title_read(title) for title in titles]

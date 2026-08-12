"""Title membership routes — tagging an artist on a title (E01-S03).

Routing only: validate the request shape, call one service method, shape the response.
Every rule about who may tag whom lives in `TitleMembershipService`.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, TitleMembershipServiceDep
from app.models.title_membership import TitleMembership
from app.schemas.title_membership import (
    ArtistRead,
    MembershipScope,
    TaggedArtistCreate,
    TitleMembershipCreated,
    TitleMembershipRead,
    TitleMembersView,
)

router = APIRouter(tags=["title-memberships"])

TAGGED_ARTIST_SCOPE_SUMMARY = (
    "Sees only mentions of this title that also mention them. Cannot edit title setup, "
    "and cannot see the rest of your slate."
)
AGENCY_MANAGER_SCOPE_SUMMARY = (
    "Reads and exports this title only. Cannot edit title setup, and cannot see the rest "
    "of your slate."
)

_SCOPE_SUMMARIES = {
    True: TAGGED_ARTIST_SCOPE_SUMMARY,
    False: AGENCY_MANAGER_SCOPE_SUMMARY,
}


def to_membership_read(membership: TitleMembership) -> TitleMembershipRead:
    """Assembles the response, deriving the scope the screen shows from the role."""
    return TitleMembershipRead(
        id=membership.id,
        title_id=membership.title_id,
        role=membership.role,
        status=membership.status,
        artist=(
            ArtistRead.model_validate(membership.artist) if membership.artist is not None else None
        ),
        invited_email=membership.invited_email,
        invited_handle=membership.invited_handle,
        scope=scope_for(membership),
        last_sent_at=membership.last_sent_at,
        accepted_at=membership.accepted_at,
        created_at=membership.created_at,
    )


def scope_for(membership: TitleMembership) -> MembershipScope:
    """The promise the tagging screen makes, derived from the role rather than stored."""
    can_see_only_own_mentions = membership.role.can_see_only_mentions_naming_subject
    return MembershipScope(
        can_see_only_mentions_naming_subject=can_see_only_own_mentions,
        can_edit_title_setup=membership.role.can_edit_title_setup,
        summary=_SCOPE_SUMMARIES[can_see_only_own_mentions],
    )


@router.post(
    "/titles/{title_id}/tagged-artists",
    response_model=TitleMembershipCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Tag an artist on a title and invite them",
)
async def tag_artist(
    title_id: uuid.UUID,
    payload: TaggedArtistCreate,
    membership_service: TitleMembershipServiceDep,
    current_user: CurrentUser,
) -> TitleMembershipCreated:
    membership, raw_token = await membership_service.tag_artist(title_id, payload, current_user)
    return TitleMembershipCreated(
        **to_membership_read(membership).model_dump(),
        token=raw_token,
    )


@router.get(
    "/titles/{title_id}/memberships",
    response_model=TitleMembersView,
    summary="List who has been granted access to this title",
)
async def list_title_memberships(
    title_id: uuid.UUID,
    membership_service: TitleMembershipServiceDep,
    current_user: CurrentUser,
) -> TitleMembersView:
    memberships = await membership_service.list_memberships(title_id, current_user)
    return TitleMembersView(
        memberships=[to_membership_read(membership) for membership in memberships]
    )


@router.post(
    "/titles/{title_id}/memberships/{membership_id}/resend",
    response_model=TitleMembershipCreated,
    summary="Re-issue the acceptance link for a pending membership",
)
async def resend_title_invitation(
    title_id: uuid.UUID,
    membership_id: uuid.UUID,
    membership_service: TitleMembershipServiceDep,
    current_user: CurrentUser,
) -> TitleMembershipCreated:
    membership, raw_token = await membership_service.resend_invitation(
        title_id, membership_id, current_user
    )
    return TitleMembershipCreated(
        **to_membership_read(membership).model_dump(),
        token=raw_token,
    )


@router.delete(
    "/titles/{title_id}/memberships/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Untag an artist, revoking their access immediately",
)
async def untag_artist(
    title_id: uuid.UUID,
    membership_id: uuid.UUID,
    membership_service: TitleMembershipServiceDep,
    current_user: CurrentUser,
) -> None:
    await membership_service.untag_artist(title_id, membership_id, current_user)

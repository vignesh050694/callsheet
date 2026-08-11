"""Invitation and membership routes.

Routing only: validate the request shape, call one service method, shape the response.
Who may invite whom lives in `InvitationService`.
"""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, InvitationServiceDep
from app.schemas.invitation import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationRead,
    MemberRead,
    MembersView,
)

router = APIRouter(tags=["members"])


@router.get(
    "/organizations/{organization_id}/members",
    response_model=MembersView,
    summary="Members and pending invitations for an organization",
)
async def list_members(
    organization_id: uuid.UUID,
    invitation_service: InvitationServiceDep,
    current_user: CurrentUser,
) -> MembersView:
    memberships, pending_invitations = await invitation_service.list_members(
        organization_id, current_user
    )
    return MembersView(
        members=[
            MemberRead(
                user_id=membership.user_id,
                email=membership.user.email,
                display_name=membership.user.display_name,
                role=membership.role,
                joined_at=membership.created_at,
            )
            for membership in memberships
        ],
        pending_invitations=[
            InvitationRead.model_validate(invitation) for invitation in pending_invitations
        ],
    )


@router.post(
    "/organizations/{organization_id}/invitations",
    response_model=InvitationCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Invite someone into an organization with a role",
)
async def create_invitation(
    organization_id: uuid.UUID,
    payload: InvitationCreate,
    invitation_service: InvitationServiceDep,
    current_user: CurrentUser,
) -> InvitationCreated:
    invitation, raw_token = await invitation_service.invite_member(
        organization_id, payload, current_user
    )
    return InvitationCreated(
        **InvitationRead.model_validate(invitation).model_dump(), token=raw_token
    )


@router.post(
    "/invitations/{invitation_id}/resend",
    response_model=InvitationCreated,
    summary="Re-issue a pending invitation",
)
async def resend_invitation(
    invitation_id: uuid.UUID,
    invitation_service: InvitationServiceDep,
    current_user: CurrentUser,
) -> InvitationCreated:
    invitation, raw_token = await invitation_service.resend_invitation(invitation_id, current_user)
    return InvitationCreated(
        **InvitationRead.model_validate(invitation).model_dump(), token=raw_token
    )


@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a pending invitation",
)
async def cancel_invitation(
    invitation_id: uuid.UUID,
    invitation_service: InvitationServiceDep,
    current_user: CurrentUser,
) -> None:
    await invitation_service.cancel_invitation(invitation_id, current_user)


@router.post(
    "/invitations/accept",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Accept an invitation and join the organization",
)
async def accept_invitation(
    payload: InvitationAccept,
    invitation_service: InvitationServiceDep,
    current_user: CurrentUser,
) -> None:
    await invitation_service.accept_invitation(payload.token, current_user)

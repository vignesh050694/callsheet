"""Current-user routes.

Routing only: resolve the caller, call one service method, shape the response.
"""

from fastapi import APIRouter

from app.api.deps import CurrentUser, UserServiceDep
from app.schemas.organization import OrganizationRead
from app.schemas.user import CurrentUserRead, MembershipRead, UserRead

router = APIRouter(prefix="/me", tags=["me"])


@router.get(
    "",
    response_model=CurrentUserRead,
    summary="The signed-in user and the organizations they belong to",
)
async def read_current_user(
    current_user: CurrentUser,
    user_service: UserServiceDep,
) -> CurrentUserRead:
    memberships = await user_service.list_memberships(current_user.id)
    return CurrentUserRead(
        user=UserRead.model_validate(current_user),
        memberships=[
            MembershipRead(
                id=membership.id,
                role=membership.role,
                organization=OrganizationRead.model_validate(membership.organization),
                created_at=membership.created_at,
            )
            for membership in memberships
        ],
    )

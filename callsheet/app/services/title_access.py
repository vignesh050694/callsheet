"""Who may read a title, decided in one place (E01-S05).

Before this, three services each answered the question themselves — `TitleService`,
`CollectionStatusService`, and `TitlePreviewService` all held the same "is the caller a
member of the owning organization" check. That was correct while ownership was the only
way in. It stops being correct the moment a title can be shared, and three copies of a
rule is three chances to add the new case to two of them.

The story's requirement is that enforcement lives at the query layer rather than in the
UI, and that a title nobody shared with you is indistinguishable from one that does not
exist. Both are properties of this module, and every title read goes through it.

The 404-for-everything rule is deliberate and applies even to callers who plainly exist:
an unannounced film is a secret, and "403 Forbidden" confirms the film is real. Only a
caller who can already see the title gets a 403, and only for an action they lack the
rights for — a distinction they can verify for themselves, so hiding it would be a lie
rather than a precaution.
"""

import enum
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import PermissionDeniedError, ResourceNotFoundError
from app.models.title import Title
from app.models.title_membership import TitleMembership, TitleRole
from app.models.user import User
from app.repositories.membership_repository import MembershipRepository
from app.repositories.title_membership_repository import TitleMembershipRepository
from app.repositories.title_repository import TitleRepository

_logger = structlog.get_logger(__name__)

TITLE_NOT_FOUND_MESSAGE = "Title {id} was not found"
NOT_AN_OWNER_MESSAGE = "Only an owner of the organization that owns this title can do that"
READ_ONLY_GRANT_MESSAGE = (
    "Your access to this title is read-only — it does not include changing its setup"
)


class TitleAccessKind(enum.StrEnum):
    """How a caller reaches a title. The reason matters, not just the yes or no."""

    OWNING_ORGANIZATION = "owning_organization"
    SHARED_MEMBERSHIP = "shared_membership"


class TitleAccess:
    """A resolved answer: the title, and what the caller is allowed to do with it."""

    def __init__(
        self,
        title: Title,
        kind: TitleAccessKind,
        *,
        can_administer: bool,
        membership: TitleMembership | None = None,
    ) -> None:
        self.title = title
        self.kind = kind
        self.can_administer = can_administer
        self.membership = membership

    @property
    def is_shared_grant(self) -> bool:
        """True when the caller is outside the owning organization."""
        return self.kind is TitleAccessKind.SHARED_MEMBERSHIP

    @property
    def can_see_other_members(self) -> bool:
        """A shared title grants no sight of who else is on it.

        The story's Notes call this out directly: a grant must not become a window into
        the owning organization's member list or its other entities. Lateral visibility
        is the thing scoped access exists to prevent, so it is refused by role rather
        than by hiding a button.
        """
        return self.kind is TitleAccessKind.OWNING_ORGANIZATION


class TitleAccessPolicy:
    def __init__(self, session: AsyncSession) -> None:
        self._title_repository = TitleRepository(session)
        self._membership_repository = MembershipRepository(session)
        self._title_membership_repository = TitleMembershipRepository(session)

    async def require_readable(self, title_id: uuid.UUID, caller: User) -> TitleAccess:
        """Resolves read access, or raises the same 404 a missing title raises."""
        title = await self._title_repository.get_by_id(title_id)
        if title is None:
            raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title_id))
        return await self.resolve_for_title(title, caller)

    async def resolve_for_title(self, title: Title, caller: User) -> TitleAccess:
        """The same decision, for a title the caller already loaded."""
        membership = await self._membership_repository.get_for_user_and_organization(
            caller.id, title.organization_id
        )
        if membership is not None:
            return TitleAccess(
                title,
                TitleAccessKind.OWNING_ORGANIZATION,
                can_administer=membership.role.can_administer_organization,
            )

        shared = await self._find_shared_grant(title.id, caller)
        if shared is not None:
            # Neither shared role administers anything — `can_edit_title_setup` is False
            # for both, and this reads it from the role rather than restating it.
            return TitleAccess(
                title,
                TitleAccessKind.SHARED_MEMBERSHIP,
                can_administer=shared.role.can_edit_title_setup,
                membership=shared,
            )

        _logger.warning(
            "title.access.denied",
            title_id=str(title.id),
            user_id=str(caller.id),
        )
        raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title.id))

    async def require_owning_organization(
        self, title_id: uuid.UUID, caller: User
    ) -> TitleAccess:
        """Read access held through the owning organization, and nothing else.

        For the surfaces that describe *other people's* relationship to a title — the
        member list, the access log. A shared grant gets the plain 404 a stranger gets,
        not a 403, because 403 is a statement about rights the caller might expect to
        have, and an agency was never offered any view of who else is on the title. It
        would also confirm the log exists, which is itself the lateral signal the story's
        Notes forbid.
        """
        access = await self.require_readable(title_id, caller)
        if access.can_see_other_members:
            return access

        _logger.warning(
            "title.access.lateral_denied",
            title_id=str(title_id),
            user_id=str(caller.id),
            kind=str(access.kind),
        )
        raise ResourceNotFoundError(TITLE_NOT_FOUND_MESSAGE.format(id=title_id))

    async def require_administrable(
        self,
        title_id: uuid.UUID,
        caller: User,
        *,
        owner_message: str = NOT_AN_OWNER_MESSAGE,
    ) -> TitleAccess:
        """Read access plus the right to change the title. Owners only.

        A caller who holds a shared grant gets 403 rather than 404: they can already see
        the title, so pretending it is missing would be a lie they could disprove.

        `owner_message` is the caller's, because the *decision* is shared but the sentence
        is not. "Only an owner can change this title's release date or milestones" tells a
        viewer which control to stop reaching for; collapsing every refusal into one
        generic line would lose that, and it is the kind of regression that passes review
        because the status code is still correct.
        """
        access = await self.require_readable(title_id, caller)
        if access.can_administer:
            return access

        _logger.warning(
            "title.access.not_administrable",
            title_id=str(title_id),
            user_id=str(caller.id),
            kind=str(access.kind),
        )
        raise PermissionDeniedError(
            READ_ONLY_GRANT_MESSAGE if access.is_shared_grant else owner_message
        )

    async def _find_shared_grant(self, title_id: uuid.UUID, caller: User) -> TitleMembership | None:
        """An active grant reaching this caller, directly or through their organization.

        Checked in that order because a person can hold both — an artist tagged on a
        title their agency also manages — and the direct grant is the narrower one, so
        resolving to it keeps the caller's access no wider than it has to be.
        """
        direct = await self._title_membership_repository.get_active_for_subject_user(
            title_id, caller.id
        )
        if direct is not None:
            return direct

        organization_ids = [
            membership.organization_id
            for membership in await self._membership_repository.list_for_user(caller.id)
        ]
        if not organization_ids:
            return None
        return await self._title_membership_repository.get_active_for_subject_organizations(
            title_id, organization_ids
        )


def is_agency_role(role: TitleRole) -> bool:
    return role is TitleRole.AGENCY_MANAGER

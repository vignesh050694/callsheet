"""Model package. Import every model here so Alembic autogenerate sees the full metadata."""

from app.models.base import Base
from app.models.invitation import Invitation, InvitationStatus
from app.models.membership import Membership, MembershipRole
from app.models.mention import Mention, MentionRawPayload
from app.models.mention_analysis import MentionAnalysis
from app.models.organization import Organization, OrganizationType
from app.models.title import Title, TitleMilestone, TitleTerm, TitleTermType
from app.models.user import User

__all__ = [
    "Base",
    "Invitation",
    "InvitationStatus",
    "Membership",
    "MembershipRole",
    "Mention",
    "MentionAnalysis",
    "MentionRawPayload",
    "Organization",
    "OrganizationType",
    "Title",
    "TitleMilestone",
    "TitleTerm",
    "TitleTermType",
    "User",
]

"""Model package. Import every model here so Alembic autogenerate sees the full metadata."""

from app.models.access_audit import AccessAuditAction, AccessAuditEvent
from app.models.artist import Artist, ArtistIdentityTerm, ArtistTermType
from app.models.base import Base
from app.models.collection_run import (
    CollectionRun,
    CollectionRunStatus,
    CollectionRunTrigger,
)
from app.models.invitation import Invitation, InvitationStatus
from app.models.membership import Membership, MembershipRole
from app.models.mention import Mention, MentionRawPayload
from app.models.mention_analysis import MentionAnalysis
from app.models.mention_query_match import MentionQueryMatch
from app.models.organization import Organization, OrganizationType
from app.models.title import Title, TitleMilestone, TitleTerm, TitleTermType
from app.models.title_membership import (
    TitleMembership,
    TitleMembershipStatus,
    TitleRole,
)
from app.models.user import User

__all__ = [
    "AccessAuditAction",
    "AccessAuditEvent",
    "Artist",
    "ArtistIdentityTerm",
    "ArtistTermType",
    "Base",
    "CollectionRun",
    "CollectionRunStatus",
    "CollectionRunTrigger",
    "Invitation",
    "InvitationStatus",
    "Membership",
    "MembershipRole",
    "Mention",
    "MentionAnalysis",
    "MentionQueryMatch",
    "MentionRawPayload",
    "Organization",
    "OrganizationType",
    "Title",
    "TitleMembership",
    "TitleMembershipStatus",
    "TitleMilestone",
    "TitleRole",
    "TitleTerm",
    "TitleTermType",
    "User",
]

"""Delivery of invitation emails (E01-S02).

v1 has no mail transport. This is the seam a real one plugs into: the service calls
`send_invitation` and does not care how the message travels. The default implementation
logs the acceptance link — never the token itself, which would put a live credential in
the log file — and the raw token comes back on the create/resend response instead.
"""

import structlog

from app.models.invitation import Invitation
from app.models.title_membership import TitleMembership

_logger = structlog.get_logger(__name__)


class InvitationNotifier:
    """Logs what would have been sent. Replace with a mailer when one exists."""

    async def send_invitation(self, invitation: Invitation, organization_name: str) -> None:
        _logger.info(
            "invitation.email.sent",
            invitation_id=str(invitation.id),
            recipient=invitation.email,
            organization=organization_name,
            role=str(invitation.role),
        )

    async def send_title_invitation(
        self, membership: TitleMembership, title_name: str, artist_name: str
    ) -> None:
        """The tagged-artist invitation (E01-S03).

        A separate method rather than a widened `send_invitation`: this message is about a
        title and names the person tagged, and a real mailer will render it from a
        different template. `channel` records which contact the tag supplied, because a
        handle-only tag cannot be delivered by mail and the owner has to pass the link on.
        """
        _logger.info(
            "title_invitation.email.sent",
            membership_id=str(membership.id),
            recipient=membership.invited_email or membership.invited_handle,
            channel="email" if membership.invited_email else "handle",
            title=title_name,
            artist=artist_name,
            role=str(membership.role),
        )

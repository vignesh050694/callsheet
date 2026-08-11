"""Delivery of invitation emails (E01-S02).

v1 has no mail transport. This is the seam a real one plugs into: the service calls
`send_invitation` and does not care how the message travels. The default implementation
logs the acceptance link — never the token itself, which would put a live credential in
the log file — and the raw token comes back on the create/resend response instead.
"""

import structlog

from app.models.invitation import Invitation

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

/**
 * Shows the acceptance link for a freshly minted invitation (E01-S02).
 *
 * v1 has no mail transport, so the link cannot reach the recipient on its own. Until a
 * mailer exists, the owner has to pass it on by hand — which means the UI has to show it
 * exactly once, at the moment it is issued. The raw token is never listed again: the
 * pending-invitation list carries no token, by design.
 */

import { buildAcceptanceUrl } from '@/lib/invitations'
import type { InvitationCreated } from '@/types/api'

export function InvitationLink({ invitation }: { invitation: InvitationCreated }) {
  const acceptanceUrl = buildAcceptanceUrl(invitation.token, globalThis.location?.origin ?? '')

  return (
    <div className="border-ink-200 bg-ink-50 mt-3 rounded-md border px-4 py-3">
      <p className="text-sm font-medium">Send this link to {invitation.email}</p>
      <p className="text-ink-600 mt-1 text-xs">
        Shown once. No email is sent yet — copy it now, or resend the invitation to issue a new
        link.
      </p>
      <code className="text-ink-900 mt-2 block break-all font-mono text-xs">{acceptanceUrl}</code>
    </div>
  )
}

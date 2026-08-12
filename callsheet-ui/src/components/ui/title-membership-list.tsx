/**
 * Who has been let into a title, and on what terms (E01-S03).
 *
 * UI invariant D: the status of a membership is chrome, not sentiment. Pending and active
 * read as neutral chips distinguished by their label and weight, never by a green/amber
 * pair — a coloured status chip on this screen would spend part of the colour budget that
 * the sentiment scale needs to own once mentions land.
 *
 * Names here arrive in Tamil and Telugu script and handles run long, so every cell wraps
 * rather than truncating to a fixed width.
 */

import type { TitleMembership, TitleMembershipStatus, TitleRole } from '@/types/api'

const ROLE_LABELS: Record<TitleRole, string> = {
  tagged_artist: 'Tagged artist',
  agency_manager: 'Agency manager',
}

/** A membership names either a person or an organization, never both. */
function subjectNameOf(membership: TitleMembership): string {
  return (
    membership.artist?.display_name ?? membership.subject_organization?.name ?? 'Unknown subject'
  )
}

const STATUS_LABELS: Record<TitleMembershipStatus, string> = {
  pending: 'Invited — not yet accepted',
  active: 'Active',
  revoked: 'Revoked',
}

/** Weight and border carry the distinction; the palette stays neutral. See invariant D. */
const STATUS_STYLES: Record<TitleMembershipStatus, string> = {
  pending: 'border-ink-200 text-ink-600 border-dashed',
  active: 'border-ink-300 text-ink-900 font-medium',
  revoked: 'border-ink-200 text-ink-400 line-through',
}

function StatusChip({ status }: { status: TitleMembershipStatus }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-xs whitespace-nowrap ${STATUS_STYLES[status]}`}
    >
      {STATUS_LABELS[status]}
    </span>
  )
}

function ContactLine({ membership }: { membership: TitleMembership }) {
  const contact = membership.invited_email ?? membership.invited_handle
  if (!contact) return null

  return (
    <p className="text-ink-400 mt-0.5 text-xs break-all">
      Invited via {membership.invited_email ? 'email' : 'handle'} · {contact}
    </p>
  )
}

export function TitleMembershipList({
  memberships,
  canManage,
  onUntag,
  isUntagging,
  onResend,
  isResending,
}: {
  memberships: TitleMembership[]
  canManage: boolean
  onUntag: (membership: TitleMembership) => void
  isUntagging: boolean
  onResend: (membership: TitleMembership) => void
  isResending: boolean
}) {
  if (memberships.length === 0) {
    return (
      <p className="text-ink-400 text-sm">
        Nobody outside your organization has been given access to this title yet.
      </p>
    )
  }

  return (
    <ul className="divide-ink-200 divide-y">
      {memberships.map((membership) => (
        <li key={membership.id} className="flex flex-wrap items-start gap-3 py-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium break-words">{subjectNameOf(membership)}</p>
            <p className="text-ink-400 mt-0.5 text-xs">{ROLE_LABELS[membership.role]}</p>
            <ContactLine membership={membership} />
            {/* The restriction, restated on the row rather than only at tagging time —
                this list is where an owner checks what an external party can see. */}
            <p className="text-ink-600 mt-1 text-xs">{membership.scope.summary}</p>
          </div>

          <div className="flex items-center gap-2">
            <StatusChip status={membership.status} />
            {canManage &&
              membership.status === 'pending' &&
              membership.role === 'tagged_artist' && (
                // Only for a pending row: the raw token is shown once and never stored, so
                // re-issuing is the only way to recover a link — and an accepted membership
                // has nothing left to redeem.
                <button
                  type="button"
                  onClick={() => onResend(membership)}
                  disabled={isResending}
                  className="border-ink-200 hover:border-ink-400 rounded-md border px-2 py-1 text-xs disabled:opacity-40"
                >
                  Get link
                </button>
              )}
            {canManage && membership.role === 'tagged_artist' && (
              <button
                type="button"
                onClick={() => onUntag(membership)}
                disabled={isUntagging}
                className="border-ink-200 hover:border-ink-400 rounded-md border px-2 py-1 text-xs disabled:opacity-40"
              >
                Untag
              </button>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}

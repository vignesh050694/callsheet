/**
 * Members screen (E01-S02).
 *
 * Who is in the organization, who has been asked, and — for owners — the controls to
 * invite, resend and cancel. Owner-only controls are hidden here for clarity, but the
 * server enforces the same rule independently: hiding a button is not a permission.
 *
 * UI invariants: no aggregate, no mention text, no outbound public action, and nothing
 * encoded by colour, so none of the four platform invariants apply. Role is shown as a
 * neutral text chip rather than a coloured badge, to leave saturated colour to sentiment.
 */

import { useState } from 'react'

import { InvitationLink } from '@/components/ui/invitation-link'
import { EmptyState, ErrorState, LoadingState } from '@/components/ui/status-message'
import { useCurrentUser } from '@/hooks/use-current-user'
import {
  useCancelInvitation,
  useInviteMember,
  useMembers,
  useResendInvitation,
} from '@/hooks/use-members'
import type { Invitation, MembershipRole } from '@/types/api'

const ROLE_LABELS: Record<MembershipRole, string> = {
  owner: 'Owner',
  viewer: 'Viewer',
}

const ROLE_OPTIONS: MembershipRole[] = ['owner', 'viewer']

function RoleChip({ role }: { role: MembershipRole }) {
  return (
    <span className="border-ink-200 text-ink-600 rounded border px-2 py-0.5 text-xs">
      {ROLE_LABELS[role]}
    </span>
  )
}

function InviteForm({ organizationId }: { organizationId: string }) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<MembershipRole>('viewer')
  const inviteMember = useInviteMember(organizationId)

  const isSubmittable = email.trim().length > 0 && !inviteMember.isPending

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!isSubmittable) return

    inviteMember.mutate({ email: email.trim(), role }, { onSuccess: () => setEmail('') })
  }

  return (
    <form onSubmit={handleSubmit} className="border-ink-200 rounded-lg border bg-white p-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex-1">
          <span className="text-ink-600 block text-xs font-medium">Work email</span>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="publicity@sunpictures.com"
            className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
          />
        </label>

        <label>
          <span className="text-ink-600 block text-xs font-medium">Role</span>
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as MembershipRole)}
            className="border-ink-200 mt-1 rounded-md border px-3 py-2 text-sm outline-none"
          >
            {ROLE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {ROLE_LABELS[option]}
              </option>
            ))}
          </select>
        </label>

        <button
          type="submit"
          disabled={!isSubmittable}
          className="bg-brand-500 hover:bg-brand-600 rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          {inviteMember.isPending ? 'Sending…' : 'Send invitation'}
        </button>
      </div>

      <p className="text-ink-400 mt-2 text-xs">
        A viewer can read every title in this organization and change nothing.
      </p>

      {inviteMember.isSuccess && <InvitationLink invitation={inviteMember.data} />}

      {inviteMember.isError && (
        <div className="mt-3">
          <ErrorState error={inviteMember.error} />
        </div>
      )}
    </form>
  )
}

function PendingInvitationRow({
  invitation,
  organizationId,
  canManage,
}: {
  invitation: Invitation
  organizationId: string
  canManage: boolean
}) {
  const resendInvitation = useResendInvitation(organizationId)
  const cancelInvitation = useCancelInvitation(organizationId)
  const isBusy = resendInvitation.isPending || cancelInvitation.isPending
  const actionError = resendInvitation.error ?? cancelInvitation.error

  return (
    <>
      <tr className="border-ink-200 border-t">
        <td className="px-4 py-2">{invitation.email}</td>
        <td className="px-4 py-2">
          <RoleChip role={invitation.role} />
        </td>
        <td className="text-ink-400 px-4 py-2 text-xs">
          sent {new Date(invitation.last_sent_at).toLocaleDateString()}
        </td>
        {/* Owner-only controls. The server refuses these for a viewer regardless. */}
        {canManage && (
          <td className="px-4 py-2 text-right">
            <button
              type="button"
              onClick={() => resendInvitation.mutate(invitation.id)}
              disabled={isBusy}
              className="text-brand-600 hover:text-brand-500 text-xs font-medium disabled:opacity-40"
            >
              Resend
            </button>
            <button
              type="button"
              onClick={() => cancelInvitation.mutate(invitation.id)}
              disabled={isBusy}
              className="text-ink-600 hover:text-ink-900 ml-4 text-xs font-medium disabled:opacity-40"
            >
              Cancel
            </button>
          </td>
        )}
      </tr>
      {/* A resend mints a new token and invalidates the old link, so it has to be shown
          here too — otherwise resending would quietly break the invitation. */}
      {resendInvitation.isSuccess && (
        <tr>
          <td colSpan={canManage ? 4 : 3} className="px-4 pb-3">
            <InvitationLink invitation={resendInvitation.data} />
          </td>
        </tr>
      )}
      {actionError && (
        <tr>
          <td colSpan={canManage ? 4 : 3} className="px-4 pb-3">
            <ErrorState error={actionError} />
          </td>
        </tr>
      )}
    </>
  )
}

export function MembersPage() {
  const currentUser = useCurrentUser()
  const membership = currentUser.data?.memberships[0]
  const organizationId = membership?.organization.id
  const members = useMembers(organizationId)

  if (currentUser.isPending || members.isPending) return <LoadingState label="Loading members…" />
  if (currentUser.isError) return <ErrorState error={currentUser.error} />
  if (!membership || !organizationId) {
    return <EmptyState>Create your studio workspace before inviting anyone.</EmptyState>
  }
  if (members.isError) return <ErrorState error={members.error} />

  const isOwner = membership.role === 'owner'
  const { members: currentMembers, pending_invitations: pendingInvitations } = members.data

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Members</h1>
        <p className="text-ink-600 mt-1 text-sm">
          {membership.organization.name} — everyone with access to this workspace.
        </p>
      </div>

      {isOwner && <InviteForm organizationId={organizationId} />}

      <div className="border-ink-200 overflow-hidden rounded-lg border bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-ink-50 text-ink-600 text-xs uppercase">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Email</th>
              <th className="px-4 py-2 font-medium">Role</th>
            </tr>
          </thead>
          <tbody>
            {currentMembers.map((member) => (
              <tr key={member.user_id} className="border-ink-200 border-t">
                <td className="px-4 py-2 font-medium">{member.display_name}</td>
                <td className="text-ink-600 px-4 py-2">{member.email}</td>
                <td className="px-4 py-2">
                  <RoleChip role={member.role} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <h2 className="text-sm font-semibold">Pending invitations</h2>
        {pendingInvitations.length === 0 ? (
          <div className="mt-2">
            <EmptyState>No invitations waiting to be accepted.</EmptyState>
          </div>
        ) : (
          <div className="border-ink-200 mt-2 overflow-hidden rounded-lg border bg-white">
            <table className="w-full text-left text-sm">
              <thead className="bg-ink-50 text-ink-600 text-xs uppercase">
                <tr>
                  <th className="px-4 py-2 font-medium">Email</th>
                  <th className="px-4 py-2 font-medium">Role</th>
                  <th className="px-4 py-2 font-medium">Sent</th>
                  {isOwner && <th className="px-4 py-2" />}
                </tr>
              </thead>
              <tbody>
                {pendingInvitations.map((invitation) => (
                  <PendingInvitationRow
                    key={invitation.id}
                    invitation={invitation}
                    organizationId={organizationId}
                    canManage={isOwner}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}

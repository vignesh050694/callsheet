/**
 * Share one title with one agency (E01-S05).
 *
 * The story's third Given is a design constraint, not a nicety: the form makes the studio
 * pick a title explicitly and offers no "share my whole slate" shortcut. This screen is
 * per-title for that reason — the grant is scoped by construction, so there is no path
 * where a distracted click shares an unannounced film.
 *
 * The scope the agency will get is stated before the grant is made, the same way the
 * tagging screen states an artist's, and for the same reason: the studio is handing
 * access to an outside organization and should read the terms first.
 *
 * UI invariants: no aggregate (A n/a), no mention text (B n/a), no AI-to-post path
 * (C n/a). Invariant D: nothing here encodes meaning in colour.
 */

import { useState } from 'react'

import { ErrorState } from '@/components/ui/status-message'
import { useOrganizations } from '@/hooks/use-organizations'
import { useShareTitleWithAgency } from '@/hooks/use-title-sharing'
import type { Organization } from '@/types/api'

export const AGENCY_SCOPE_NOTICE =
  'An agency manager can read and export this title only. They cannot edit its setup, ' +
  'cannot see the rest of your slate, and cannot see who else has access.'

export function AgencyShareForm({ titleId, titleName }: { titleId: string; titleName: string }) {
  const organizations = useOrganizations()
  const shareTitle = useShareTitleWithAgency(titleId)
  const [agencyId, setAgencyId] = useState('')

  // Only agencies. The server refuses anything else, and offering a production house here
  // would be offering an action that cannot succeed.
  const agencies: Organization[] =
    organizations.data?.items.filter(
      (organization) => organization.organization_type === 'agency',
    ) ?? []

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!agencyId || shareTitle.isPending) return
    shareTitle.mutate({ agency_organization_id: agencyId }, { onSuccess: () => setAgencyId('') })
  }

  if (organizations.isPending) return null
  if (agencies.length === 0) {
    return (
      <p className="text-ink-400 text-sm">
        No agency organizations exist yet. An agency needs its own workspace before a title can be
        shared with it.
      </p>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <p className="border-ink-200 bg-ink-50 text-ink-600 rounded-md border px-3 py-2 text-xs">
        {AGENCY_SCOPE_NOTICE}
      </p>

      <label className="block">
        <span className="text-ink-600 block text-xs font-medium">
          Share <span className="font-semibold">{titleName}</span> with
        </span>
        <select
          value={agencyId}
          onChange={(event) => setAgencyId(event.target.value)}
          required
          className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
        >
          <option value="">Pick an agency…</option>
          {agencies.map((agency) => (
            <option key={agency.id} value={agency.id}>
              {agency.name}
            </option>
          ))}
        </select>
        <span className="text-ink-400 mt-1 block text-xs">
          This title only. Sharing is per title — nothing else on your slate is included, and there
          is no option to share all of them.
        </span>
      </label>

      <button
        type="submit"
        disabled={!agencyId || shareTitle.isPending}
        className="bg-brand-500 hover:bg-brand-600 w-full rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
      >
        {shareTitle.isPending ? 'Sharing…' : 'Share this title'}
      </button>

      {shareTitle.isError && <ErrorState error={shareTitle.error} />}
    </form>
  )
}

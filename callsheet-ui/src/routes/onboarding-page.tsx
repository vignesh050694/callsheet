/**
 * First-run workspace setup (E01-S01).
 *
 * Shown only to a user with no memberships. Submitting creates the organization and the
 * caller's owner membership in one request; the workspace gate then routes them on to
 * their (empty) title list.
 *
 * UI invariants: this screen shows no aggregate, no mention text, no outbound action,
 * and encodes nothing by colour, so none of the four platform invariants apply. The one
 * accent is the existing brand colour on the submit button.
 */

import { useState } from 'react'

import { ErrorState } from '@/components/ui/status-message'
import { useCreateOrganization } from '@/hooks/use-organizations'
import { toSlug } from '@/lib/slug'
import type { OrganizationType } from '@/types/api'

const MIN_STUDIO_NAME_LENGTH = 2

/** Only Production House is offered in v1; Agency workspaces arrive with E07. */
const ORGANIZATION_TYPE_OPTIONS: { value: OrganizationType; label: string }[] = [
  { value: 'production_house', label: 'Production House' },
]

export function OnboardingPage() {
  const [studioName, setStudioName] = useState('')
  const [organizationType, setOrganizationType] = useState<OrganizationType>('production_house')
  const createOrganization = useCreateOrganization()

  const slug = toSlug(studioName)
  const isNameUsable = studioName.trim().length >= MIN_STUDIO_NAME_LENGTH && slug.length >= 2
  const isSubmittable = isNameUsable && !createOrganization.isPending

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!isSubmittable) return

    createOrganization.mutate({
      name: studioName.trim(),
      slug,
      organization_type: organizationType,
    })
  }

  return (
    <section className="mx-auto max-w-lg">
      <h1 className="text-xl font-semibold tracking-tight">Set up your studio workspace</h1>
      <p className="text-ink-600 mt-1 text-sm">
        Every title you track will sit under this workspace, owned by your studio rather than by any
        one person&apos;s login.
      </p>

      <form
        onSubmit={handleSubmit}
        className="border-ink-200 mt-6 space-y-4 rounded-lg border bg-white p-5"
      >
        <label className="block">
          <span className="text-ink-600 block text-xs font-medium">Studio name</span>
          <input
            value={studioName}
            onChange={(event) => setStudioName(event.target.value)}
            placeholder="Sun Pictures"
            autoFocus
            className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
          />
          {slug && <span className="text-ink-400 mt-1 block font-mono text-xs">slug: {slug}</span>}
        </label>

        <label className="block">
          <span className="text-ink-600 block text-xs font-medium">Organization type</span>
          <select
            value={organizationType}
            onChange={(event) => setOrganizationType(event.target.value as OrganizationType)}
            className="border-ink-200 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
          >
            {ORGANIZATION_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <button
          type="submit"
          disabled={!isSubmittable}
          className="bg-brand-500 hover:bg-brand-600 w-full rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          {createOrganization.isPending ? 'Creating workspace…' : 'Create workspace'}
        </button>

        {createOrganization.isError && <ErrorState error={createOrganization.error} />}
      </form>
    </section>
  )
}

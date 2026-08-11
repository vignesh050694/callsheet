import { useState } from 'react'

import { EmptyState, ErrorState, LoadingState } from '@/components/ui/status-message'
import { useCreateOrganization, useOrganizations } from '@/hooks/use-organizations'
import type { OrganizationType } from '@/types/api'

const ORGANIZATION_TYPE_LABELS: Record<OrganizationType, string> = {
  production_house: 'Production house',
  agency: 'Agency',
}

/** Lowercase, hyphenated, no trailing separators — matches the backend's slug pattern. */
function toSlug(rawName: string): string {
  return rawName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function CreateOrganizationForm() {
  const [name, setName] = useState('')
  const [organizationType, setOrganizationType] = useState<OrganizationType>('production_house')
  const createOrganization = useCreateOrganization()

  const slug = toSlug(name)
  const isSubmittable = slug.length >= 2 && !createOrganization.isPending

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!isSubmittable) return

    createOrganization.mutate(
      { name: name.trim(), slug, organization_type: organizationType },
      { onSuccess: () => setName('') },
    )
  }

  return (
    <form onSubmit={handleSubmit} className="border-ink-200 rounded-lg border bg-white p-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex-1">
          <span className="text-ink-600 block text-xs font-medium">Name</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Sun Pictures"
            className="border-ink-200 focus:border-brand-500 mt-1 w-full rounded-md border px-3 py-2 text-sm outline-none"
          />
        </label>

        <label>
          <span className="text-ink-600 block text-xs font-medium">Type</span>
          <select
            value={organizationType}
            onChange={(event) => setOrganizationType(event.target.value as OrganizationType)}
            className="border-ink-200 mt-1 rounded-md border px-3 py-2 text-sm outline-none"
          >
            <option value="production_house">Production house</option>
            <option value="agency">Agency</option>
          </select>
        </label>

        <button
          type="submit"
          disabled={!isSubmittable}
          className="bg-brand-500 hover:bg-brand-600 rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          {createOrganization.isPending ? 'Creating…' : 'Create'}
        </button>
      </div>

      {slug && <p className="text-ink-400 mt-2 font-mono text-xs">slug: {slug}</p>}
      {createOrganization.isError && (
        <div className="mt-3">
          <ErrorState error={createOrganization.error} />
        </div>
      )}
    </form>
  )
}

function OrganizationTable() {
  const { data, isPending, isError, error } = useOrganizations()

  if (isPending) return <LoadingState label="Loading organizations…" />
  if (isError) return <ErrorState error={error} />
  if (data.items.length === 0) {
    return <EmptyState>No organizations yet. Create the first one above.</EmptyState>
  }

  return (
    <div className="border-ink-200 overflow-hidden rounded-lg border bg-white">
      <table className="w-full text-left text-sm">
        <thead className="bg-ink-50 text-ink-600 text-xs uppercase">
          <tr>
            <th className="px-4 py-2 font-medium">Name</th>
            <th className="px-4 py-2 font-medium">Slug</th>
            <th className="px-4 py-2 font-medium">Type</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((organization) => (
            <tr key={organization.id} className="border-ink-200 border-t">
              <td className="px-4 py-2 font-medium">{organization.name}</td>
              <td className="text-ink-600 px-4 py-2 font-mono text-xs">{organization.slug}</td>
              <td className="text-ink-600 px-4 py-2">
                {ORGANIZATION_TYPE_LABELS[organization.organization_type]}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function OrganizationsPage() {
  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Organizations</h1>
        <p className="text-ink-600 mt-1 text-sm">
          Production houses and agencies. Everything else hangs off one of these.
        </p>
      </div>

      <CreateOrganizationForm />
      <OrganizationTable />
    </section>
  )
}

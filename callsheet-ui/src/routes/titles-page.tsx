/**
 * Title list for the caller's organization (E01-S01).
 *
 * Where onboarding lands you. Titles themselves are E02, so the list is empty by
 * construction and this screen exists for its empty state: the "Create your first
 * title" call to action that tells a new owner what to do next.
 */

import { useCurrentUser } from '@/hooks/use-current-user'
import { ErrorState, LoadingState } from '@/components/ui/status-message'

export function TitlesPage() {
  const { data, isPending, isError, error } = useCurrentUser()

  if (isPending) return <LoadingState label="Loading your workspace…" />
  if (isError) return <ErrorState error={error} />

  const ownedOrganization = data.memberships[0]?.organization

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Titles</h1>
        {ownedOrganization && <p className="text-ink-600 mt-1 text-sm">{ownedOrganization.name}</p>}
      </div>

      <div className="border-ink-200 rounded-lg border border-dashed px-6 py-12 text-center">
        <p className="text-sm font-medium">No titles yet</p>
        <p className="text-ink-400 mx-auto mt-1 max-w-sm text-sm">
          Add the film or show you want to track. We&apos;ll start collecting mentions against its
          name, aliases, and official hashtags.
        </p>
        <button
          type="button"
          disabled
          title="Title setup arrives with E02"
          className="bg-brand-500 mt-5 rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          Create your first title
        </button>
      </div>
    </section>
  )
}

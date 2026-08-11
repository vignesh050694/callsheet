/**
 * Title list for the caller's organization (E01-S01, filled in by E02-S01).
 *
 * Where onboarding lands you. Each row shows the identity set the title collects against,
 * because a title that looks fine by name can still be collecting the wrong film — the
 * term count is the thing worth seeing at a glance.
 *
 * UI invariants: no aggregate, no mention text, no outbound action, nothing encoded by
 * colour, so none of the four platform invariants apply.
 */

import { Link } from 'react-router-dom'

import { ErrorState, LoadingState } from '@/components/ui/status-message'
import { useCurrentUser } from '@/hooks/use-current-user'
import { useTitles } from '@/hooks/use-titles'
import type { Title } from '@/types/api'

const MAX_PREVIEW_TERMS = 6

function IdentityPreview({ title }: { title: Title }) {
  const previewTerms = title.collection_terms.slice(0, MAX_PREVIEW_TERMS)
  const remainingCount = title.collection_terms.length - previewTerms.length

  return (
    <div className="mt-2 flex flex-wrap items-center gap-1">
      {previewTerms.map((term) => (
        <span
          key={term}
          className="border-ink-200 text-ink-600 rounded border px-2 py-0.5 font-mono text-xs"
        >
          {term}
        </span>
      ))}
      {remainingCount > 0 && <span className="text-ink-400 text-xs">+{remainingCount} more</span>}
    </div>
  )
}

function CreateTitleLink({ label }: { label: string }) {
  return (
    <Link
      to="/titles/new"
      className="bg-brand-500 hover:bg-brand-600 inline-block rounded-md px-4 py-2 text-sm font-medium text-white"
    >
      {label}
    </Link>
  )
}

/**
 * The call to action is owner-only, matching the server. A viewer sent to the setup form
 * could fill the whole thing in and only learn on submit that they were never allowed to
 * — so they get told what the screen is waiting for instead.
 */
function EmptyTitleList({ canCreate }: { canCreate: boolean }) {
  return (
    <div className="border-ink-200 rounded-lg border border-dashed px-6 py-12 text-center">
      <p className="text-sm font-medium">No titles yet</p>
      <p className="text-ink-400 mx-auto mt-1 max-w-sm text-sm">
        {canCreate
          ? "Add the film or show you want to track. We'll start collecting mentions against its name, aliases, and official hashtags."
          : 'An owner of this organization needs to add a title before there is anything to see here.'}
      </p>
      {canCreate && (
        <div className="mt-5">
          <CreateTitleLink label="Create your first title" />
        </div>
      )}
    </div>
  )
}

export function TitlesPage() {
  const currentUser = useCurrentUser()
  const membership = currentUser.data?.memberships[0]
  const organizationId = membership?.organization.id
  const titles = useTitles(organizationId)

  if (currentUser.isPending) return <LoadingState label="Loading your workspace…" />
  if (currentUser.isError) return <ErrorState error={currentUser.error} />

  const isOwner = membership?.role === 'owner'

  return (
    <section className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Titles</h1>
          {membership && (
            <p className="text-ink-600 mt-1 text-sm">{membership.organization.name}</p>
          )}
        </div>
        {isOwner && titles.data && titles.data.items.length > 0 && (
          <CreateTitleLink label="Add a title" />
        )}
      </div>

      {titles.isPending && <LoadingState label="Loading titles…" />}
      {titles.isError && <ErrorState error={titles.error} />}

      {titles.data &&
        (titles.data.items.length === 0 ? (
          <EmptyTitleList canCreate={isOwner} />
        ) : (
          <ul className="space-y-3">
            {titles.data.items.map((title) => (
              <li key={title.id} className="border-ink-200 rounded-lg border bg-white px-4 py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm font-medium">{title.name}</span>
                  <span className="text-ink-400 text-xs">
                    {title.collection_terms.length} identity terms
                    {!title.has_anchor_term && ' · no anchor term'}
                  </span>
                </div>
                <IdentityPreview title={title} />
              </li>
            ))}
          </ul>
        ))}
    </section>
  )
}

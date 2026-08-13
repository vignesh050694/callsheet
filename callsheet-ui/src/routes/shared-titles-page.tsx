/**
 * The read-only list of titles shared with this account (E01-S04).
 *
 * What an artist sees after accepting. It is deliberately not `TitlesPage` with the
 * buttons hidden: that screen is an owner's workspace, and reusing it would mean every
 * future owner-only control added there has to remember to hide itself here. A separate
 * screen that renders nothing but titles cannot leak an action by omission.
 *
 * No collection status, no identity set, no member list — a tagged artist is not a
 * stakeholder in how the title is configured, and the story scopes them to coverage.
 *
 * UI invariants: no aggregate (A n/a — the mention counts on the owner's list are
 * deliberately absent here), no mention text (B n/a), no outbound action (C n/a).
 * Invariant D: nothing encodes meaning in colour.
 */

import { ErrorState, LoadingState } from '@/components/ui/status-message'
import { useSharedTitles } from '@/hooks/use-title-invitations'
import { formatDay } from '@/lib/release-phase'

export function SharedTitlesPage() {
  const sharedTitles = useSharedTitles()

  if (sharedTitles.isPending) return <LoadingState label="Loading your titles…" />
  if (sharedTitles.isError) return <ErrorState error={sharedTitles.error} />

  return (
    <section className="mx-auto max-w-2xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Shared with you</h1>
        <p className="text-ink-600 mt-1 text-sm">
          Titles a production house has tagged you on. You see the coverage, not the setup.
        </p>
      </div>

      {sharedTitles.data.length === 0 ? (
        <p className="text-ink-400 text-sm">
          Nothing has been shared with you yet. A production house has to tag you on a title and
          send an invitation.
        </p>
      ) : (
        <ul className="border-ink-200 divide-ink-200 divide-y rounded-lg border bg-white">
          {sharedTitles.data.map((title) => (
            <li key={title.id} className="px-5 py-4">
              <p className="text-sm font-medium break-words">{title.name}</p>
              <p className="text-ink-600 mt-1 text-xs">Releasing {formatDay(title.release_date)}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

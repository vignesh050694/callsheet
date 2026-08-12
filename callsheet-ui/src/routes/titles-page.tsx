/**
 * Title list for the caller's organization (E01-S01, filled in by E02-S01).
 *
 * Where onboarding lands you. Each row shows the identity set the title collects against,
 * because a title that looks fine by name can still be collecting the wrong film — the
 * term count is the thing worth seeing at a glance.
 *
 * Since E03-S01 each row also carries a collection line. This is the screen a studio is on
 * in the minutes after finishing setup, so it is where "collection started on its own" has
 * to be visible; the Title Dashboard the story names is E05 and does not exist yet.
 *
 * UI invariants: the mention count is an aggregate, and it is labelled unsegmented in
 * `collection-status.tsx` because account typing does not arrive until E04-S03. No mention
 * text, no outbound action, and nothing encoded by colour.
 */

import { Link } from 'react-router-dom'

import { TitleCollectionStatusLine } from '@/components/ui/collection-status'
import { ErrorState, LoadingState } from '@/components/ui/status-message'
import { useCollectionStatus } from '@/hooks/use-collection-status'
import { useCurrentUser } from '@/hooks/use-current-user'
import { useTitles } from '@/hooks/use-titles'
import { formatDay } from '@/lib/release-phase'
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

/**
 * One title, with its own collection status query.
 *
 * Per row rather than one batched call for the list. The endpoint is title-scoped, the
 * lists here are a page of twenty at most, and each row's status polls on its own schedule
 * — a title still waiting for its first mentions refetches while its settled neighbours
 * sit still, which a single shared query could not express.
 */
function TitleRow({ title, isOwner }: { title: Title; isOwner: boolean }) {
  const collectionStatus = useCollectionStatus(title.id)

  return (
    <li className="border-ink-200 rounded-lg border bg-white px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">{title.name}</span>
        <span className="text-ink-400 text-xs">
          {title.collection_terms.length} identity terms
          {!title.has_anchor_term && ' · no anchor term'}
        </span>
      </div>
      <div className="text-ink-600 mt-1 flex flex-wrap items-baseline gap-x-2 text-xs">
        <span>Releasing {formatDay(title.release_date)}</span>
        {title.milestones.length > 0 && (
          <span className="text-ink-400">
            · {title.milestones.length} {title.milestones.length === 1 ? 'milestone' : 'milestones'}
          </span>
        )}
        <Link
          to={`/titles/${title.id}/schedule`}
          className="text-ink-400 hover:text-ink-900 underline underline-offset-2"
        >
          {isOwner ? 'Edit schedule' : 'View schedule'}
        </Link>
        <Link
          to={`/titles/${title.id}/cast`}
          className="text-ink-400 hover:text-ink-900 underline underline-offset-2"
        >
          Cast access
        </Link>
        {/* Owners only: everything on that screen is a decision about what the title
            collects, and the server refuses it to a read-only grant anyway. */}
        {isOwner && (
          <Link
            to={`/titles/${title.id}/aliases`}
            className="text-ink-400 hover:text-ink-900 underline underline-offset-2"
          >
            Alias suggestions
          </Link>
        )}
      </div>
      <TitleCollectionStatusLine
        status={collectionStatus.data}
        isPending={collectionStatus.isPending}
      />
      <IdentityPreview title={title} />
    </li>
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
              <TitleRow key={title.id} title={title} isOwner={isOwner} />
            ))}
          </ul>
        ))}
    </section>
  )
}

/**
 * Alias suggestions — approving what the audience actually calls this title (E02-S04).
 *
 * The screen exists because an identity set typed at setup goes stale the moment fans
 * coin a tag. Twenty posts from one live run produced seven organic hashtags and a
 * misspelt director; none of them could have been declared in advance.
 *
 * UI invariants, worked through:
 *
 * - **A (account-type segmentation).** Every candidate carries a mention count, and a
 *   count is an aggregate. Account typing is E04-S03 and has not run, so this one cannot
 *   be attributed to a segment — it is labelled unsegmented rather than folded silently
 *   into an organic number. The scan coverage is stated for the same reason: once a
 *   campaign outgrows the scan cap the counts describe the recent window, not the
 *   campaign, and the screen has to say which.
 * - **B (language provenance).** Sample posts are real corpus text. The platform's
 *   language tag is shown as an unverified claim and never used to filter or hide a
 *   candidate — it was wrong on roughly half the non-English content in the live sample.
 * - **C (approval gate).** Nothing is approved in bulk and nothing is approved
 *   automatically, however high the count. Each Approve acts on one named term with its
 *   evidence beside it, which is the point of the screen.
 * - **D (colour budget).** Entirely greyscale. Approve and Reject are weight and border,
 *   not green and red — red belongs to negative sentiment, and nothing here is scored.
 */

import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ErrorState, LoadingState } from '@/components/ui/status-message'
import {
  useAliasSuggestions,
  useApproveAliasSuggestion,
  useRejectAliasSuggestion,
  useRestoreRejectedAlias,
} from '@/hooks/use-alias-suggestions'
import { useTitle } from '@/hooks/use-titles'
import { formatDay } from '@/lib/release-phase'
import type { AliasApproval, AliasCandidate, AliasRejection } from '@/types/api'

const POST_TIME_FORMAT = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

const SKELETON_ROWS = [0, 1, 2]

const KIND_LABELS: Record<AliasCandidate['kind'], string> = {
  hashtag: 'Hashtag',
  name_variant: 'Name variant',
}

/**
 * A hashtag joins the set as a hashtag and is queried bare; a name variant is an alias and
 * is queried anchored to a person. The two are not interchangeable, so the kind the list
 * showed is the kind that gets approved.
 */
const TERM_TYPE_FOR_KIND: Record<AliasCandidate['kind'], 'hashtag' | 'alias'> = {
  hashtag: 'hashtag',
  name_variant: 'alias',
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="border-ink-200 text-ink-600 rounded border px-2 py-0.5 text-xs">
      {children}
    </span>
  )
}

function SuggestionSkeleton() {
  return (
    <ul className="mt-3 space-y-2">
      {SKELETON_ROWS.map((row) => (
        <li key={row} className="border-ink-200 rounded-md border p-3">
          <div className="bg-ink-200 h-3 w-40 animate-pulse rounded" />
          <div className="bg-ink-200 mt-2 h-3 w-full animate-pulse rounded" />
          <div className="bg-ink-200 mt-1 h-3 w-2/3 animate-pulse rounded" />
        </li>
      ))}
    </ul>
  )
}

interface CandidateCardProps {
  candidate: AliasCandidate
  isBusy: boolean
  onApprove: () => void
  onReject: () => void
}

function CandidateCard({ candidate, isBusy, onApprove, onReject }: CandidateCardProps) {
  const { sample } = candidate

  return (
    <li className="border-ink-200 rounded-md border p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-ink-900 min-w-0 font-mono text-sm font-medium break-words">
          {candidate.value}
        </p>
        <div className="flex flex-wrap items-center gap-1">
          <Chip>{KIND_LABELS[candidate.kind]}</Chip>
          <Chip>
            {candidate.mention_count} {candidate.mention_count === 1 ? 'post' : 'posts'} ·
            unsegmented
          </Chip>
        </div>
      </div>

      {candidate.resembles && (
        <p className="text-ink-400 mt-1 text-xs">
          Looks like a misspelling of <span className="font-mono">{candidate.resembles}</span>,
          which this title already declares.
        </p>
      )}

      {sample ? (
        <div className="border-ink-200 bg-ink-50 mt-2 rounded border p-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-ink-600 min-w-0 text-xs font-medium break-words">
              {sample.author_display_name}{' '}
              <span className="text-ink-400 font-normal">{sample.author_handle}</span>
            </p>
            <p className="text-ink-400 text-xs">
              {POST_TIME_FORMAT.format(new Date(sample.posted_at))}
            </p>
          </div>
          <p className="text-ink-600 mt-1 text-sm break-words whitespace-pre-wrap">{sample.text}</p>
          <div className="mt-1 flex flex-wrap items-center gap-1">
            {sample.platform_reported_language && (
              <Chip>{sample.platform_reported_language} · platform-reported, unverified</Chip>
            )}
            {sample.permalink && (
              <a
                href={sample.permalink}
                target="_blank"
                rel="noreferrer"
                className="text-ink-600 text-xs underline"
              >
                Open post
              </a>
            )}
          </div>
        </div>
      ) : (
        <p className="text-ink-400 mt-2 text-xs">
          The post this was sampled from is no longer in the corpus. The count still stands.
        </p>
      )}

      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onApprove}
          disabled={isBusy}
          className="bg-ink-900 hover:bg-ink-600 rounded-md px-3 py-1 text-xs font-medium text-white disabled:opacity-40"
        >
          Approve
        </button>
        <button
          type="button"
          onClick={onReject}
          disabled={isBusy}
          className="border-ink-200 text-ink-600 hover:border-ink-400 rounded-md border px-3 py-1 text-xs disabled:opacity-40"
        >
          Not my title
        </button>
      </div>
    </li>
  )
}

function ApprovalReceipt({ approval }: { approval: AliasApproval }) {
  return (
    <p className="border-ink-200 bg-ink-50 text-ink-600 mt-3 rounded-md border px-3 py-2 text-xs">
      <span className="font-mono">{approval.term.value}</span> joined the identity set. The next
      collection cycle queries it, and {approval.rematched_mentions}{' '}
      {approval.rematched_mentions === 1 ? 'post' : 'posts'} already collected{' '}
      {approval.rematched_mentions === 1 ? 'was' : 'were'} credited to it from{' '}
      {approval.scanned_mentions} stored — nothing was fetched again, so this cost nothing.
    </p>
  )
}

function RejectedList({
  rejections,
  onRestore,
  isBusy,
}: {
  rejections: AliasRejection[]
  onRestore: (rejectionId: string) => void
  isBusy: boolean
}) {
  return (
    <div className="border-ink-200 mt-4 border-t pt-3">
      <p className="text-ink-600 text-xs font-medium">
        Refused for this title. These are never suggested again.
      </p>
      <div className="mt-1 flex flex-wrap gap-1">
        {rejections.map((rejection) => (
          <button
            key={rejection.id}
            type="button"
            onClick={() => onRestore(rejection.id)}
            disabled={isBusy}
            title="Allow this to be suggested again"
            className="border-ink-200 text-ink-600 hover:border-ink-400 rounded border px-2 py-0.5 font-mono text-xs disabled:opacity-40"
          >
            {rejection.value} <span aria-hidden="true">↺</span>
            <span className="sr-only">Allow this suggestion again</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export function TitleAliasesPage() {
  const { titleId } = useParams<{ titleId: string }>()
  const title = useTitle(titleId)
  const suggestions = useAliasSuggestions(titleId)
  const approve = useApproveAliasSuggestion(titleId)
  const reject = useRejectAliasSuggestion(titleId)
  const restore = useRestoreRejectedAlias(titleId)

  // The last approval's receipt, kept so the studio sees what it was worth. Cleared on the
  // next action so a stale number never sits under a different decision.
  const [receipt, setReceipt] = useState<AliasApproval | null>(null)

  const isBusy = approve.isPending || reject.isPending || restore.isPending

  function handleApprove(candidate: AliasCandidate) {
    setReceipt(null)
    approve.mutate(
      { value: candidate.value, term_type: TERM_TYPE_FOR_KIND[candidate.kind] },
      { onSuccess: setReceipt },
    )
  }

  function handleReject(candidate: AliasCandidate) {
    setReceipt(null)
    reject.mutate({ value: candidate.value, kind: candidate.kind })
  }

  function handleRestore(rejectionId: string) {
    setReceipt(null)
    restore.mutate(rejectionId)
  }

  if (title.isPending) return <LoadingState label="Loading title…" />
  if (title.isError) return <ErrorState error={title.error} />
  if (!title.data) return <ErrorState error={new Error('Title not found')} />

  const data = suggestions.data
  const isTruncated = Boolean(data && data.scanned_mentions < data.corpus_size)

  return (
    <section className="mx-auto max-w-2xl space-y-6">
      <div>
        <Link to="/" className="text-ink-400 hover:text-ink-900 text-xs">
          ← Back to titles
        </Link>
        <h1 className="mt-2 text-xl font-semibold tracking-tight">{title.data.name}</h1>
        <p className="text-ink-600 mt-1 text-sm">Releasing {formatDay(title.data.release_date)}</p>
      </div>

      <section className="border-ink-200 rounded-md border p-4">
        <h2 className="text-sm font-medium">Alias suggestions</h2>
        <p className="text-ink-400 mt-1 text-xs">
          Hashtags and name spellings this title&rsquo;s own corpus is using that its identity set
          does not claim. Approving one adds it to the set, so the next collection cycle queries it
          — and credits it against posts already collected without paying to fetch them again.
        </p>

        {suggestions.isPending && <SuggestionSkeleton />}
        {suggestions.isError && (
          <div className="mt-3">
            <ErrorState error={suggestions.error} />
          </div>
        )}

        {data && (
          <>
            <p className="border-ink-200 bg-ink-50 text-ink-600 mt-3 rounded-md border px-3 py-2 text-xs">
              Unsegmented counts. These posts have not been account-typed yet, so trade trackers,
              distributors and ticketing accounts are counted alongside audience posts.{' '}
              {isTruncated
                ? `Ranked over the ${data.scanned_mentions} most recent of ${data.corpus_size} collected posts — counts describe that window, not the whole campaign.`
                : `Ranked over all ${data.corpus_size} collected posts.`}
            </p>

            {approve.isError && (
              <div className="mt-3">
                <ErrorState error={approve.error} />
              </div>
            )}
            {reject.isError && (
              <div className="mt-3">
                <ErrorState error={reject.error} />
              </div>
            )}
            {restore.isError && (
              <div className="mt-3">
                <ErrorState error={restore.error} />
              </div>
            )}
            {receipt && <ApprovalReceipt approval={receipt} />}

            {data.candidates.length === 0 ? (
              <p className="text-ink-400 mt-3 text-xs">
                Nothing new in the corpus. Either the identity set already claims every term people
                are using, or collection has not run for this title yet — suggestions appear after
                the first polling cycle.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {data.candidates.map((candidate) => (
                  <CandidateCard
                    key={`${candidate.kind}:${candidate.normalized_value}`}
                    candidate={candidate}
                    isBusy={isBusy}
                    onApprove={() => handleApprove(candidate)}
                    onReject={() => handleReject(candidate)}
                  />
                ))}
              </ul>
            )}

            {data.rejections.length > 0 && (
              <RejectedList
                rejections={data.rejections}
                onRestore={handleRestore}
                isBusy={isBusy}
              />
            )}
          </>
        )}
      </section>
    </section>
  )
}

/**
 * The mentions feed, and excluding a term from it (E02-S05).
 *
 * The screen exists for one judgement: is this post about my film? The live run answered
 * "not always" — a post carrying `#DC #DareDevil` matched a Tamil production's short name
 * and was about a superhero. Three shared letters put another franchise's conversation
 * into a film's numbers.
 *
 * The confirmation step is the whole design. A studio does not confirm the string
 * `#DareDevil`; they confirm "this removes 4 of your 312 posts", because `#DC` looks
 * identical on screen and would remove all 312. The count is measured against the real
 * corpus before the rule exists, and quoted posts come with it — a number alone is not
 * reviewable.
 *
 * UI invariants, worked through:
 *
 * - **A (account-type segmentation).** Two aggregates here: the corpus totals and the
 *   impact count. Account typing is E04-S03 and has not run, so neither can be attributed
 *   to a segment. Both are labelled unsegmented rather than folded silently into an
 *   organic number.
 * - **B (language provenance).** Real corpus text. The platform's language tag is shown
 *   as an unverified claim and never used to filter or hide a post — it was wrong on
 *   roughly half the non-English content in the live sample.
 * - **C (approval gate).** Nothing posts anything. The gate that matters here is the
 *   opposite direction: an exclusion is destructive to a number, so it takes a measured
 *   count and a second, explicit confirmation, and it is reversible from this screen.
 * - **D (colour budget).** Entirely greyscale. An excluded post dims and is labelled; no
 *   red, because red belongs to negative sentiment and nothing here has been scored.
 */

import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ErrorState, LoadingState } from '@/components/ui/status-message'
import {
  useCreateExclusion,
  useMeasureExclusionImpact,
  useMentionFeed,
  useRemoveExclusion,
  useTitleExclusions,
} from '@/hooks/use-mentions'
import { useTitle } from '@/hooks/use-titles'
import { formatDay } from '@/lib/release-phase'
import type { Exclusion, ExclusionImpact, Mention } from '@/types/api'

const POST_TIME_FORMAT = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

const SKELETON_ROWS = [0, 1, 2]

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="border-ink-200 text-ink-600 rounded border px-2 py-0.5 text-xs">
      {children}
    </span>
  )
}

function FeedSkeleton() {
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

function PostBody({ mention }: { mention: Mention }) {
  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-ink-900 min-w-0 text-sm font-medium break-words">
          {mention.author_display_name}{' '}
          <span className="text-ink-400 font-normal">{mention.author_handle}</span>
        </p>
        <p className="text-ink-400 text-xs">
          {POST_TIME_FORMAT.format(new Date(mention.posted_at))}
        </p>
      </div>
      <p className="text-ink-600 mt-1 text-sm break-words whitespace-pre-wrap">{mention.text}</p>
    </>
  )
}

interface MentionCardProps {
  mention: Mention
  isBusy: boolean
  onPropose: (term: string) => void
}

function MentionCard({ mention, isBusy, onPropose }: MentionCardProps) {
  const [isMarked, setIsMarked] = useState(false)

  return (
    <li
      className={`border-ink-200 rounded-md border p-3 ${mention.excluded_by_term ? 'bg-ink-50 opacity-60' : ''}`}
    >
      <PostBody mention={mention} />

      <div className="mt-2 flex flex-wrap items-center gap-1">
        <span className="text-ink-400 text-xs">Matched</span>
        {mention.matched_terms.length > 0 ? (
          mention.matched_terms.map((term) => <Chip key={term}>{term}</Chip>)
        ) : (
          <Chip>your search query</Chip>
        )}
        {mention.platform_reported_language && (
          <Chip>{mention.platform_reported_language} · platform-reported, unverified</Chip>
        )}
        {mention.permalink && (
          <a
            href={mention.permalink}
            target="_blank"
            rel="noreferrer"
            className="text-ink-600 text-xs underline"
          >
            Open post
          </a>
        )}
      </div>

      {mention.excluded_by_term ? (
        <p className="text-ink-400 mt-2 text-xs">
          Not counted — removed by the exclusion{' '}
          <span className="font-mono">{mention.excluded_by_term}</span>. The post is still stored,
          so lifting that rule brings it back.
        </p>
      ) : (
        <>
          <button
            type="button"
            onClick={() => setIsMarked((current) => !current)}
            aria-pressed={isMarked}
            disabled={isBusy}
            className="border-ink-200 text-ink-600 hover:border-ink-400 mt-2 rounded border px-2 py-1 text-xs disabled:opacity-40"
          >
            {isMarked ? 'Marked: not my title' : 'Not my title'}
          </button>

          {isMarked && (
            <div className="mt-2">
              {mention.candidate_exclusion_terms.length > 0 ? (
                <>
                  <p className="text-ink-400 text-xs">
                    Which term dragged this post in? You will see how many posts the rule removes
                    before it is applied.
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {mention.candidate_exclusion_terms.map((term) => (
                      <button
                        key={term}
                        type="button"
                        onClick={() => onPropose(term)}
                        disabled={isBusy}
                        className="border-ink-200 text-ink-600 hover:border-ink-400 rounded border px-2 py-0.5 font-mono text-xs disabled:opacity-40"
                      >
                        {term}
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <p className="text-ink-400 text-xs">
                  No hashtag in this post that your identity set does not already claim — there is
                  nothing here to exclude it by. Excluding an ordinary word would take out far more
                  than this post.
                </p>
              )}
            </div>
          )}
        </>
      )}
    </li>
  )
}

interface ImpactDialogProps {
  impact: ExclusionImpact
  isConfirming: boolean
  onConfirm: () => void
  onCancel: () => void
}

function ImpactDialog({ impact, isConfirming, onConfirm, onCancel }: ImpactDialogProps) {
  return (
    <section className="border-ink-900 mt-3 rounded-md border p-4">
      <h3 className="text-sm font-medium">
        Exclude <span className="font-mono">{impact.value}</span>?
      </h3>

      <p className="text-ink-600 mt-1 text-sm">
        This removes <span className="font-medium">{impact.would_remove}</span> of the{' '}
        {impact.counted_now} posts currently counted for this title, and stops future collection
        counting posts that carry it. Nothing is deleted — the posts stay stored, and lifting the
        rule brings them back without collecting again.
      </p>

      <p className="border-ink-200 bg-ink-50 text-ink-600 mt-2 rounded border px-3 py-2 text-xs">
        Unsegmented count. These posts have not been account-typed, so trade trackers, distributors
        and ticketing accounts are counted here alongside audience posts.
      </p>

      {impact.removes_everything && (
        <p className="border-ink-900 text-ink-900 mt-2 rounded border px-3 py-2 text-xs font-medium">
          This would remove every post this title has. That is almost always a term the whole corpus
          carries — check it is not part of how people refer to your film.
        </p>
      )}

      {impact.would_remove === 0 && (
        <p className="text-ink-400 mt-2 text-xs">
          Nothing already collected carries this term. The rule still applies to everything
          collected from now on.
        </p>
      )}

      {impact.samples.length > 0 && (
        <div className="mt-3">
          <p className="text-ink-600 text-xs font-medium">Posts this would remove</p>
          <ul className="mt-1 space-y-2">
            {impact.samples.map((sample) => (
              <li key={sample.id} className="border-ink-200 bg-ink-50 rounded border p-2">
                <PostBody mention={sample} />
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={onConfirm}
          disabled={isConfirming}
          className="bg-ink-900 hover:bg-ink-600 rounded-md px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          {isConfirming ? 'Excluding…' : `Exclude ${impact.value}`}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={isConfirming}
          className="border-ink-200 text-ink-600 hover:border-ink-400 rounded-md border px-3 py-1.5 text-xs disabled:opacity-40"
        >
          Cancel
        </button>
      </div>
    </section>
  )
}

function ExclusionList({
  exclusions,
  onLift,
  isBusy,
}: {
  exclusions: Exclusion[]
  onLift: (termId: string) => void
  isBusy: boolean
}) {
  return (
    <section className="border-ink-200 rounded-md border p-4">
      <h2 className="text-sm font-medium">Exclusion rules</h2>
      <p className="text-ink-400 mt-1 text-xs">
        Posts carrying these terms are not counted for this title, historic ones included. Lifting a
        rule gives its posts back — they were marked, never deleted, so nothing is re-collected.
      </p>
      <div className="mt-2 flex flex-wrap gap-1">
        {exclusions.map((exclusion) => (
          <button
            key={exclusion.id}
            type="button"
            onClick={() => onLift(exclusion.id)}
            disabled={isBusy}
            title="Lift this exclusion"
            className="border-ink-200 text-ink-600 hover:border-ink-400 rounded border px-2 py-0.5 font-mono text-xs disabled:opacity-40"
          >
            {exclusion.value} <span aria-hidden="true">×</span>
            <span className="sr-only">Lift this exclusion</span>
          </button>
        ))}
      </div>
    </section>
  )
}

export function TitleMentionsPage() {
  const { titleId } = useParams<{ titleId: string }>()
  const [includeExcluded, setIncludeExcluded] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const title = useTitle(titleId)
  const feed = useMentionFeed(titleId, includeExcluded)
  const exclusions = useTitleExclusions(titleId)
  const impact = useMeasureExclusionImpact(titleId)
  const createExclusion = useCreateExclusion(titleId)
  const removeExclusion = useRemoveExclusion(titleId)

  const isBusy = impact.isPending || createExclusion.isPending || removeExclusion.isPending

  function proposeExclusion(term: string) {
    setNotice(null)
    impact.mutate({ value: term })
  }

  function confirmExclusion(value: string) {
    createExclusion.mutate(
      { value },
      {
        onSuccess: (created) => {
          impact.reset()
          setNotice(
            `${created.term.value} is now excluded. ${created.removed_mentions} already-collected ` +
              `${created.removed_mentions === 1 ? 'post is' : 'posts are'} no longer counted, and ` +
              `future collection will not count them either. Nothing was deleted.`,
          )
        },
      },
    )
  }

  function liftExclusion(termId: string) {
    setNotice(null)
    removeExclusion.mutate(termId, {
      onSuccess: (removed) => {
        setNotice(
          `${removed.value} is no longer excluded. ${removed.restored_mentions} ` +
            `${removed.restored_mentions === 1 ? 'post is' : 'posts are'} counted again — ` +
            `nothing was collected to get them back.`,
        )
      },
    })
  }

  if (title.isPending) return <LoadingState label="Loading title…" />
  if (title.isError) return <ErrorState error={title.error} />
  if (!title.data) return <ErrorState error={new Error('Title not found')} />

  const data = feed.data

  return (
    <section className="mx-auto max-w-2xl space-y-6">
      <div>
        <Link to="/" className="text-ink-400 hover:text-ink-900 text-xs">
          ← Back to titles
        </Link>
        <h1 className="mt-2 text-xl font-semibold tracking-tight">{title.data.name}</h1>
        <p className="text-ink-600 mt-1 text-sm">Releasing {formatDay(title.data.release_date)}</p>
      </div>

      {exclusions.data && exclusions.data.length > 0 && (
        <ExclusionList exclusions={exclusions.data} onLift={liftExclusion} isBusy={isBusy} />
      )}

      <section className="border-ink-200 rounded-md border p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-medium">Mentions</h2>
          <label className="text-ink-600 flex items-center gap-1.5 text-xs">
            <input
              type="checkbox"
              checked={includeExcluded}
              onChange={(event) => setIncludeExcluded(event.target.checked)}
              className="accent-ink-900"
            />
            Show excluded posts
          </label>
        </div>

        {data && (
          <p className="border-ink-200 bg-ink-50 text-ink-600 mt-3 rounded-md border px-3 py-2 text-xs">
            Unsegmented. These posts have not been account-typed or language-checked yet, so trade
            trackers, distributors and ticketing accounts appear alongside audience posts.{' '}
            {data.counted_total === data.collected_total
              ? `${data.counted_total} collected, all counted.`
              : `${data.counted_total} counted of ${data.collected_total} collected — the difference is what your exclusion rules removed.`}
          </p>
        )}

        {notice && (
          <p className="border-ink-200 bg-ink-50 text-ink-600 mt-3 rounded-md border px-3 py-2 text-xs">
            {notice}
          </p>
        )}

        {impact.isError && (
          <div className="mt-3">
            <ErrorState error={impact.error} />
          </div>
        )}
        {createExclusion.isError && (
          <div className="mt-3">
            <ErrorState error={createExclusion.error} />
          </div>
        )}
        {removeExclusion.isError && (
          <div className="mt-3">
            <ErrorState error={removeExclusion.error} />
          </div>
        )}

        {impact.data && (
          <ImpactDialog
            impact={impact.data}
            isConfirming={createExclusion.isPending}
            onConfirm={() => confirmExclusion(impact.data.value)}
            onCancel={() => impact.reset()}
          />
        )}

        {feed.isPending && <FeedSkeleton />}
        {feed.isError && (
          <div className="mt-3">
            <ErrorState error={feed.error} />
          </div>
        )}

        {data &&
          (data.items.length === 0 ? (
            <p className="text-ink-400 mt-3 text-xs">
              Nothing collected yet. Collection starts on its own once a title exists — the first
              cycle usually lands within a day.
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {data.items.map((mention) => (
                <MentionCard
                  key={mention.id}
                  mention={mention}
                  isBusy={isBusy}
                  onPropose={proposeExclusion}
                />
              ))}
            </ul>
          ))}
      </section>
    </section>
  )
}

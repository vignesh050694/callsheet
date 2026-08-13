/**
 * Preview matches, on the setup screen (E02-S03).
 *
 * The point of this panel is that a production house finds out their film is badly
 * described in the first minute of setup, rather than from a junk dashboard a day later.
 * Everything here serves that: real post text, the terms that pulled each post in, and a
 * way to say "not my title" that turns into an exclusion rule at save time.
 *
 * UI invariants, worked through:
 *
 * - **A (account-type segmentation).** No aggregate is shown — a sample of twenty posts a
 *   human reads is not a number. But the sample is *unsegmented*, because account typing
 *   is E04 and has not run, so trade, distributor, and promotional accounts sit in it
 *   unlabelled. That is stated on the panel rather than left for the reader to assume.
 * - **B (language provenance).** The platform's language tag is shown as a claim, marked
 *   unverified, and never used to filter or hide a post. It was wrong on roughly half the
 *   non-English content in the live sample.
 * - **C (approval gate).** Nothing here posts anything. Marking a post only proposes a
 *   term, and the term still has to be chosen and then saved with the title.
 * - **D (colour budget).** Entirely greyscale. A rejected post dims and is labelled; no
 *   red, because red belongs to negative sentiment and nothing here has been scored.
 */

import { useState } from 'react'

import { ErrorState } from '@/components/ui/status-message'
import { useTitlePreview } from '@/hooks/use-title-preview'
import type { PreviewPost, TitlePreviewRequest } from '@/types/api'

const POST_TIME_FORMAT = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

const SKELETON_ROWS = [0, 1, 2]

interface MatchPreviewProps {
  draft: TitlePreviewRequest
  organizationId: string | undefined
  /** The identity set passes the anchor rule — the same gate the save button uses. */
  isPreviewable: boolean
  exclusions: string[]
  onExclusionsChange: (next: string[]) => void
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="border-ink-200 text-ink-600 rounded border px-2 py-0.5 text-xs">
      {children}
    </span>
  )
}

function PreviewSkeleton() {
  return (
    <ul className="mt-3 space-y-2">
      {SKELETON_ROWS.map((row) => (
        <li key={row} className="border-ink-200 rounded-md border p-3">
          <div className="bg-ink-200 h-3 w-32 animate-pulse rounded" />
          <div className="bg-ink-200 mt-2 h-3 w-full animate-pulse rounded" />
          <div className="bg-ink-200 mt-1 h-3 w-2/3 animate-pulse rounded" />
        </li>
      ))}
    </ul>
  )
}

interface PreviewPostCardProps {
  post: PreviewPost
  isRejected: boolean
  onToggleRejected: () => void
  exclusions: string[]
  onToggleExclusion: (term: string) => void
}

function PreviewPostCard({
  post,
  isRejected,
  onToggleRejected,
  exclusions,
  onToggleExclusion,
}: PreviewPostCardProps) {
  return (
    <li
      className={`border-ink-200 rounded-md border p-3 ${isRejected ? 'bg-ink-50 opacity-60' : ''}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-ink-900 min-w-0 text-sm font-medium break-words">
          {post.author_display_name}{' '}
          <span className="text-ink-400 font-normal">{post.author_handle}</span>
        </p>
        <p className="text-ink-400 text-xs">{POST_TIME_FORMAT.format(new Date(post.posted_at))}</p>
      </div>

      <p className="text-ink-600 mt-1 text-sm break-words whitespace-pre-wrap">{post.text}</p>

      <div className="mt-2 flex flex-wrap items-center gap-1">
        <span className="text-ink-400 text-xs">Matched</span>
        {post.matched_terms.length > 0 ? (
          post.matched_terms.map((term) => <Chip key={term}>{term}</Chip>)
        ) : (
          <Chip>your search query</Chip>
        )}
        {post.platform_reported_language && (
          <Chip>{post.platform_reported_language} · platform-reported, unverified</Chip>
        )}
        {post.permalink && (
          <a
            href={post.permalink}
            target="_blank"
            rel="noreferrer"
            className="text-ink-600 text-xs underline"
          >
            Open post
          </a>
        )}
      </div>

      <button
        type="button"
        onClick={onToggleRejected}
        aria-pressed={isRejected}
        className="border-ink-200 text-ink-600 hover:border-ink-400 mt-2 rounded border px-2 py-1 text-xs"
      >
        {isRejected ? 'Marked: not my title' : 'Not my title'}
      </button>

      {isRejected && (
        <div className="mt-2">
          {post.candidate_exclusion_terms.length > 0 ? (
            <>
              <p className="text-ink-400 text-xs">
                Exclude the term that dragged this post in. Excluded terms are saved with the title.
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {post.candidate_exclusion_terms.map((term) => {
                  const isExcluded = exclusions.includes(term)
                  return (
                    <button
                      key={term}
                      type="button"
                      onClick={() => onToggleExclusion(term)}
                      aria-pressed={isExcluded}
                      className={
                        isExcluded
                          ? 'border-ink-900 bg-ink-900 rounded border px-2 py-0.5 text-xs text-white'
                          : 'border-ink-200 text-ink-600 hover:border-ink-400 rounded border px-2 py-0.5 text-xs'
                      }
                    >
                      {isExcluded ? `Excluding ${term}` : `Exclude ${term}`}
                    </button>
                  )
                })}
              </div>
            </>
          ) : (
            <p className="text-ink-400 text-xs">
              No hashtag in this post that your identity set does not already claim — nothing to
              exclude from it.
            </p>
          )}
        </div>
      )}
    </li>
  )
}

export function MatchPreview({
  draft,
  organizationId,
  isPreviewable,
  exclusions,
  onExclusionsChange,
}: MatchPreviewProps) {
  const preview = useTitlePreview(organizationId)
  const [rejectedPostIds, setRejectedPostIds] = useState<string[]>([])

  function toggleRejected(postId: string) {
    setRejectedPostIds((current) =>
      current.includes(postId) ? current.filter((id) => id !== postId) : [...current, postId],
    )
  }

  function toggleExclusion(term: string) {
    onExclusionsChange(
      exclusions.includes(term) ? exclusions.filter((it) => it !== term) : [...exclusions, term],
    )
  }

  const posts = preview.data?.posts ?? []

  return (
    <section className="border-ink-200 rounded-md border p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">Preview matches</h2>
        <button
          type="button"
          disabled={!isPreviewable || preview.isPending}
          onClick={() => preview.mutate(draft)}
          className="border-ink-200 text-ink-900 hover:border-ink-400 rounded-md border px-3 py-1.5 text-xs font-medium disabled:opacity-40"
        >
          {preview.isPending ? 'Searching…' : 'Preview matches'}
        </button>
      </div>
      <p className="text-ink-400 mt-1 text-xs">
        One capped search on X, up to 20 recent posts. Nothing is saved and collection has not
        started — this is a sample of what your identity set would pull in.
      </p>

      {preview.isPending && <PreviewSkeleton />}
      {preview.isError && (
        <div className="mt-3">
          <ErrorState error={preview.error} />
        </div>
      )}

      {preview.isSuccess && (
        <>
          <p className="border-ink-200 bg-ink-50 text-ink-600 mt-3 rounded-md border px-3 py-2 text-xs">
            Unclassified sample. These posts have not been account-typed or language-checked yet, so
            trade trackers, distributors, and ticketing accounts appear here alongside audience
            posts. Searched <span className="font-mono">{preview.data.query}</span>.
          </p>

          {posts.length === 0 ? (
            <p className="text-ink-400 mt-3 text-xs">
              No recent posts matched. That usually means the name and anchor together are too
              narrow, or the campaign has not started talking yet — neither blocks you from saving.
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {posts.map((post) => (
                <PreviewPostCard
                  key={post.id}
                  post={post}
                  isRejected={rejectedPostIds.includes(post.id)}
                  onToggleRejected={() => toggleRejected(post.id)}
                  exclusions={exclusions}
                  onToggleExclusion={toggleExclusion}
                />
              ))}
            </ul>
          )}
        </>
      )}

      {exclusions.length > 0 && (
        <div className="border-ink-200 mt-3 border-t pt-3">
          <p className="text-ink-600 text-xs font-medium">Exclusion terms, saved with this title</p>
          <div className="mt-1 flex flex-wrap gap-1">
            {exclusions.map((term) => (
              <button
                key={term}
                type="button"
                onClick={() => toggleExclusion(term)}
                className="border-ink-200 text-ink-600 hover:border-ink-400 rounded border px-2 py-0.5 text-xs"
              >
                {term} <span aria-hidden="true">×</span>
                <span className="sr-only">Remove exclusion</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

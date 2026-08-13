/**
 * Backfilling the weeks before signup (E03-S03).
 *
 * A studio who onboards mid-campaign has a dashboard that starts on the day they happened
 * to sign up, with the teaser and the trailer sitting in a blank spot before it. This screen
 * is how they buy that stretch back.
 *
 * The shape of it is dictated by the story: pick a range, **see what it costs and how deep
 * it can go**, then confirm. The estimate is not decoration — the confirm button does not
 * exist until a quote for the exact range on screen has come back, because this is the one
 * control in the product that spends money on a click.
 *
 * The other half is honesty about what came back. Platform search endpoints serve as much
 * history as they feel like, so a backfill that asked for six weeks and reached eleven days
 * says eleven days, in the same place it says how much it cost. Concept note §6.4: label the
 * coverage gap, never hide it.
 *
 * UI invariants, checked before building:
 *
 * * **A — account-type segmentation.** The result carries a mention count, which is an
 *   aggregate over many posts. Account typing is E04-S03, so it is labelled unsegmented in
 *   visible text rather than folded into a number a reader would take for organic reach.
 * * **B — language provenance.** No mention text or language control is rendered here, so
 *   it does not apply.
 * * **C — approval friction.** Nothing here posts anything, so the governance gate does not
 *   apply — but the principle does, because the action is irreversible spending. The
 *   friction is proportionate and explicit: a quote for this exact range, its ceiling
 *   written next to the button, and a range change that withdraws the confirm until it has
 *   been re-quoted.
 * * **D — colour budget.** Entirely greyscale. The depth-limited warning is the loudest
 *   thing on this screen and it is loud through words, weight and an icon — never hue.
 *   Sentiment owns saturated colour and there is no sentiment here to spend it on.
 */

import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { ErrorState, LoadingState } from '@/components/ui/status-message'
import { useBackfillEstimate, useBackfills, useRequestBackfill } from '@/hooks/use-backfills'
import { useCurrentUser } from '@/hooks/use-current-user'
import { useTitle } from '@/hooks/use-titles'
import {
  dayCount,
  defaultRangeStart,
  endOfDayInstant,
  isUsableRange,
  lastBackfillableDay,
  startOfDayInstant,
} from '@/lib/backfill-range'
import { formatDay } from '@/lib/release-phase'
import type { Backfill, BackfillEstimate, Title } from '@/types/api'

/** Vendor prices run to fractions of a cent, so a flat two decimals would quote $0.00. */
function formatUsd(amount: number): string {
  return amount > 0 && amount < 0.01 ? `$${amount.toFixed(4)}` : `$${amount.toFixed(2)}`
}

function formatInstantDay(instant: string): string {
  return formatDay(instant.slice(0, 10))
}

/**
 * The quote, with the page cap it is derived from written out beside it.
 *
 * The cap is shown rather than kept in configuration where only an operator can see it,
 * because it is the answer to the question the price provokes — "why can't I have more?" —
 * and because it is simultaneously the depth limit and the cost limit. Concept note §7 rule
 * 2 in one sentence a studio can read.
 */
function EstimatePanel({ estimate }: { estimate: BackfillEstimate }) {
  const collectable = estimate.platforms.filter((platform) => !platform.unavailable_reason)
  const unavailable = estimate.platforms.filter((platform) => platform.unavailable_reason)

  return (
    <div className="border-ink-200 space-y-3 rounded-lg border bg-white p-5">
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-ink-600 text-xs font-medium">Estimated cost</span>
        <span className="text-lg font-semibold tabular-nums">
          up to {formatUsd(estimate.max_cost_usd)}
        </span>
      </div>

      <p className="text-ink-600 text-xs">
        {estimate.variants} {estimate.variants === 1 ? 'query' : 'queries'} from this title's
        identity set, each allowed {estimate.pages_per_query}{' '}
        {estimate.pages_per_query === 1 ? 'page' : 'pages'} of up to {estimate.page_size} posts —{' '}
        {estimate.max_calls} calls at most.
      </p>
      <p className="text-ink-400 text-xs">
        A ceiling, not a forecast. Most backfills stop early because the platform runs out of
        history to serve, and you are charged for the calls actually made.
      </p>

      {collectable.length > 0 && (
        <ul className="text-ink-600 space-y-1 text-xs">
          {collectable.map((platform) => (
            <li key={platform.platform} className="flex items-baseline justify-between gap-4">
              <span className="uppercase">{platform.platform}</span>
              <span className="text-ink-400 tabular-nums">
                {platform.calls} calls · up to {formatUsd(platform.max_cost_usd)}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Never priced at $0.00 and never dropped. A missing line reads as "included and
          free", which is the opposite of "will not run". */}
      {unavailable.map((platform) => (
        <p key={platform.platform} className="text-ink-600 text-xs">
          <span className="font-medium uppercase">{platform.platform}</span> will not be included —{' '}
          {platform.unavailable_reason}
        </p>
      ))}
    </div>
  )
}

/**
 * What the backfill managed, once it has run.
 *
 * `earliest_posted_at` before anything else. It is the answer to the question the studio
 * actually asked, and it is the number a backfill can get wrong without anything looking
 * broken.
 */
function BackfillOutcome({ backfill }: { backfill: Backfill }) {
  const isPending = backfill.status === 'queued' || backfill.status === 'running'

  return (
    <li className="border-ink-200 rounded-lg border bg-white px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <span className="text-sm font-medium">
          {formatInstantDay(backfill.requested_from)} — {formatInstantDay(backfill.requested_until)}
        </span>
        <span className="text-ink-400 text-xs">
          {isPending
            ? backfill.status === 'queued'
              ? 'Queued'
              : 'Collecting…'
            : `${backfill.pages_fetched} ${backfill.pages_fetched === 1 ? 'page' : 'pages'} · ${formatUsd(backfill.charged_cost_usd)}`}
        </span>
      </div>

      {isPending && (
        <p className="text-ink-600 mt-1 text-xs">
          Working back through the range. This screen updates on its own.
        </p>
      )}

      {!isPending && (
        <>
          <p className="text-ink-600 mt-1 text-xs">
            {backfill.unsegmented_mentions_stored.toLocaleString()} historical{' '}
            {backfill.unsegmented_mentions_stored === 1 ? 'mention' : 'mentions'} added
            {backfill.mentions_already_known > 0 &&
              ` · ${backfill.mentions_already_known.toLocaleString()} already collected, not duplicated`}
            {/* Never dropped, never abbreviated to a tooltip — a reader who sees only the
                number will read it as public conversation, which it is not until E04-S03. */}
            <span className="text-ink-400"> · unsegmented, all account types</span>
          </p>

          <p className="text-ink-900 mt-1 text-xs font-medium">
            {backfill.earliest_posted_at
              ? `Reached back to ${formatInstantDay(backfill.earliest_posted_at)}`
              : 'Reached back to nothing — no posts were returned for this range'}
          </p>

          {/* The house rule this story applies: state the depth actually achieved, rather
              than letting the request stand in for the result. */}
          {backfill.is_depth_limited && (
            <p className="text-ink-600 mt-1 flex items-start gap-1.5 text-xs">
              <span aria-hidden="true" className="mt-px">
                ⚠
              </span>
              <span>
                Short of the {formatInstantDay(backfill.requested_from)} you asked for.{' '}
                {backfill.has_reached_page_cap
                  ? 'The per-query page limit was reached before the range was covered.'
                  : 'The platform stopped serving older results — historical search depth is capped by the platform and cannot be guaranteed.'}{' '}
                Treat this stretch as a sample rather than the complete conversation.
              </span>
            </p>
          )}

          {backfill.failure_reason && (
            <p className="text-ink-600 mt-1 text-xs">— {backfill.failure_reason}</p>
          )}
        </>
      )}
    </li>
  )
}

function BackfillForm({ title }: { title: Title }) {
  const lastDay = lastBackfillableDay()
  const pastMilestones = title.milestones
    .map((milestone) => milestone.occurs_on)
    .filter((day) => day <= lastDay)

  const [fromDay, setFromDay] = useState(() => defaultRangeStart(pastMilestones))
  const [untilDay, setUntilDay] = useState(lastDay)
  // The range the current quote describes. Changing either date clears it, so the confirm
  // button can never be pressed against a price for a range that is no longer on screen.
  const [quotedRange, setQuotedRange] = useState<string | null>(null)

  const estimate = useBackfillEstimate(title.id)
  const requestBackfill = useRequestBackfill(title.id)

  const rangeKey = `${fromDay}..${untilDay}`
  const isRangeUsable = isUsableRange(fromDay, untilDay)
  const isQuoted = quotedRange === rangeKey && estimate.data !== undefined

  function changeRange(next: { from?: string; until?: string }) {
    if (next.from !== undefined) setFromDay(next.from)
    if (next.until !== undefined) setUntilDay(next.until)
    setQuotedRange(null)
    estimate.reset()
    requestBackfill.reset()
  }

  function handleEstimate(event: React.FormEvent) {
    event.preventDefault()
    if (!isRangeUsable) return
    estimate.mutate(
      {
        requested_from: startOfDayInstant(fromDay),
        requested_until: endOfDayInstant(untilDay),
      },
      { onSuccess: () => setQuotedRange(rangeKey) },
    )
  }

  function handleConfirm() {
    if (!isQuoted) return
    requestBackfill.mutate({
      requested_from: startOfDayInstant(fromDay),
      requested_until: endOfDayInstant(untilDay),
    })
  }

  return (
    <form onSubmit={handleEstimate} className="space-y-4">
      <div className="border-ink-200 space-y-4 rounded-lg border bg-white p-5">
        <div className="flex flex-wrap gap-4">
          <label className="block">
            <span className="text-ink-600 block text-xs font-medium">From</span>
            <input
              type="date"
              value={fromDay}
              max={untilDay}
              onChange={(event) => changeRange({ from: event.target.value })}
              required
              className="border-ink-200 focus:border-brand-500 mt-1 rounded-md border px-3 py-2 text-sm outline-none"
            />
          </label>
          <label className="block">
            <span className="text-ink-600 block text-xs font-medium">To</span>
            <input
              type="date"
              value={untilDay}
              max={lastDay}
              onChange={(event) => changeRange({ until: event.target.value })}
              required
              className="border-ink-200 focus:border-brand-500 mt-1 rounded-md border px-3 py-2 text-sm outline-none"
            />
          </label>
        </div>

        <p className="text-ink-400 text-xs">
          {isRangeUsable
            ? `${dayCount(fromDay, untilDay).toLocaleString()} days, both ends included. Anything in this range you already hold is recognised and not collected twice.`
            : `Pick a start on or before the end date, ending no later than ${formatDay(lastDay)} — today is still being collected live.`}
        </p>

        <button
          type="submit"
          disabled={!isRangeUsable || estimate.isPending}
          className="border-ink-200 hover:border-ink-400 w-full rounded-md border px-4 py-2 text-sm font-medium disabled:opacity-40"
        >
          {estimate.isPending ? 'Working out the cost…' : 'Estimate this range'}
        </button>
        {estimate.isError && <ErrorState error={estimate.error} />}
      </div>

      {isQuoted && estimate.data && (
        <>
          <EstimatePanel estimate={estimate.data} />
          <button
            type="button"
            onClick={handleConfirm}
            disabled={requestBackfill.isPending || !estimate.data.max_calls}
            className="bg-brand-500 hover:bg-brand-600 w-full rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
          >
            {requestBackfill.isPending
              ? 'Starting…'
              : `Backfill this range — up to ${formatUsd(estimate.data.max_cost_usd)}`}
          </button>
          {!estimate.data.max_calls && (
            <p className="text-ink-600 text-xs">
              No platform can be collected from right now, so there is nothing to run.
            </p>
          )}
          {requestBackfill.isError && <ErrorState error={requestBackfill.error} />}
        </>
      )}
    </form>
  )
}

export function TitleBackfillPage() {
  const { titleId } = useParams<{ titleId: string }>()
  const currentUser = useCurrentUser()
  const title = useTitle(titleId)
  const backfills = useBackfills(titleId)

  if (currentUser.isPending || title.isPending) return <LoadingState label="Loading title…" />
  if (currentUser.isError) return <ErrorState error={currentUser.error} />
  if (title.isError) return <ErrorState error={title.error} />
  if (!title.data) return <ErrorState error={new Error('Title not found')} />

  const membership = currentUser.data?.memberships.find(
    (candidate) => candidate.organization.id === title.data.organization_id,
  )
  const isOwner = membership?.role === 'owner'

  return (
    <section className="mx-auto max-w-2xl space-y-6">
      <div>
        <Link to="/" className="text-ink-400 hover:text-ink-900 text-xs">
          ← Back to titles
        </Link>
        <h1 className="mt-2 text-xl font-semibold tracking-tight">Backfill history</h1>
        <p className="text-ink-600 mt-1 text-sm">{title.data.name}</p>
        <p className="text-ink-400 mt-2 text-xs">
          Collection covers everything from the day this title was created onwards. A backfill
          reaches into the conversation before that, so a campaign you had already been running
          shows up on your charts. How far back the platforms will actually go is theirs to decide,
          not ours — whatever is reached is reported exactly.
        </p>
      </div>

      {isOwner ? (
        <BackfillForm key={title.data.id} title={title.data} />
      ) : (
        <p className="text-ink-400 text-sm">
          Only an owner of this organization can start a backfill, because it spends against the
          workspace's collection budget.
        </p>
      )}

      <div className="space-y-2">
        <h2 className="text-ink-600 text-xs font-medium">Previous backfills</h2>
        {backfills.isPending && <LoadingState label="Loading backfills…" />}
        {backfills.isError && <ErrorState error={backfills.error} />}
        {backfills.data &&
          (backfills.data.items.length === 0 ? (
            <p className="text-ink-400 text-xs">None yet.</p>
          ) : (
            <ul className="space-y-2">
              {backfills.data.items.map((backfill) => (
                <BackfillOutcome key={backfill.id} backfill={backfill} />
              ))}
            </ul>
          ))}
      </div>
    </section>
  )
}

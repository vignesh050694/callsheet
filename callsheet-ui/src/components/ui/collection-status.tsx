/**
 * The collection line on a title row (E03-S01).
 *
 * A studio that has just finished setup is looking at a title with no numbers on it. This
 * says which of the three reasons that is: it has not collected yet, it collected and the
 * conversation has not started, or it has stopped collecting and needs a human. Those are
 * indistinguishable without it, and only the last one is a problem.
 *
 * UI invariants, checked before building:
 *
 * * **A — account-type segmentation.** This shows a count over many mentions, so it is an
 *   aggregate. Account typing does not exist until E04-S03, so it cannot be attributed to
 *   the organic segment and is therefore labelled `unsegmented` in the visible text rather
 *   than folded silently into a number a reader would assume was organic. The skill's rule
 *   for exactly this case: show it flagged, do not hide it and do not launder it.
 * * **B — language provenance.** No mention text is rendered here, so it does not apply.
 * * **C — approval friction.** Nothing here produces an outbound action. There is
 *   deliberately no "collect now" control: collection is not something anyone triggers.
 * * **D — colour budget.** Entirely greyscale. The sentiment scale owns saturated colour
 *   and nothing on this line competes with it; the stalled state is distinguished by an
 *   icon and its words, never by hue alone. Since E03-S02 the same rule binds the cadence
 *   phase: release week is *not* a red chip. Three phases rendered as a traffic light
 *   would be the single loudest thing on a screen whose loudest thing has to be sentiment,
 *   and it would encode by hue something that is already written in words.
 *
 * Freshness is shown because this is polled data — the "last checked" half is as much a
 * part of the reading as the count.
 *
 * The cadence phase is here rather than on a settings screen because it is the answer to
 * "why is this number moving faster than it was yesterday" (E03-S02), which is a question
 * asked while looking at the number.
 */

import { describeCadencePhase, describePollingRate } from '@/lib/cadence-phase'
import type { TitleCollectionStatus } from '@/types/api'

const MILLISECONDS_PER_MINUTE = 60_000
const MINUTES_PER_HOUR = 60
const HOURS_PER_DAY = 24

/**
 * A rough, always-past relative time. Deliberately coarse: to the minute is precise enough
 * to answer "is this thing running", and anything finer would rerender constantly to show
 * a number nobody is reading that closely.
 */
function describeElapsed(instant: string, now: number): string {
  const minutes = Math.floor((now - Date.parse(instant)) / MILLISECONDS_PER_MINUTE)
  if (!Number.isFinite(minutes)) return 'recently'
  if (minutes < 1) return 'just now'
  if (minutes < MINUTES_PER_HOUR) return `${minutes}m ago`
  const hours = Math.floor(minutes / MINUTES_PER_HOUR)
  if (hours < HOURS_PER_DAY) return `${hours}h ago`
  return `${Math.floor(hours / HOURS_PER_DAY)}d ago`
}

function describeUpcoming(instant: string, now: number): string {
  const minutes = Math.ceil((Date.parse(instant) - now) / MILLISECONDS_PER_MINUTE)
  if (!Number.isFinite(minutes)) return 'soon'
  if (minutes <= 0) return 'due now'
  if (minutes < MINUTES_PER_HOUR) return `in ${minutes}m`
  const hours = Math.round(minutes / MINUTES_PER_HOUR)
  return hours < HOURS_PER_DAY ? `in ${hours}h` : `in ${Math.round(hours / HOURS_PER_DAY)}d`
}

/** A quiet dot rather than a colour chip — see invariant D above. */
function StatusDot({ isLive }: { isLive: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={
        isLive
          ? 'bg-ink-400 inline-block h-1.5 w-1.5 shrink-0 rounded-full'
          : 'border-ink-400 inline-block h-1.5 w-1.5 shrink-0 rounded-full border'
      }
    />
  )
}

function StalledLine({ status }: { status: TitleCollectionStatus }) {
  return (
    <span className="text-ink-900 inline-flex items-center gap-1.5 font-medium">
      <StatusDot isLive={false} />
      Not collecting
      {status.last_run_failure_reason && (
        <span className="text-ink-600 font-normal">— {status.last_run_failure_reason}</span>
      )}
    </span>
  )
}

export function CollectionStatusLine({
  status,
  now = Date.now(),
}: {
  status: TitleCollectionStatus
  now?: number
}) {
  if (status.is_stalled) {
    return (
      <p className="text-ink-600 mt-2 text-xs">
        <StalledLine status={status} />
      </p>
    )
  }

  return (
    <p className="text-ink-600 mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
      {status.is_awaiting_first_results ? (
        <span className="text-ink-900 inline-flex items-center gap-1.5 font-medium">
          <StatusDot isLive />
          Collecting your first mentions
        </span>
      ) : (
        <span className="text-ink-900 inline-flex items-center gap-1.5 font-medium">
          <StatusDot isLive />
          {status.unsegmented_mention_count.toLocaleString()}{' '}
          {status.unsegmented_mention_count === 1 ? 'mention' : 'mentions'}
        </span>
      )}

      {/* Never dropped, never abbreviated to a tooltip. A reader who sees only the number
          will read it as public conversation, which it is not until E04-S03 segments it. */}
      {!status.is_awaiting_first_results && (
        <span className="text-ink-400">· unsegmented, all account types</span>
      )}

      {status.last_finished_at && (
        <span className="text-ink-400">
          · checked {describeElapsed(status.last_finished_at, now)}
        </span>
      )}
      {status.next_run_at && (
        <span className="text-ink-400">· next {describeUpcoming(status.next_run_at, now)}</span>
      )}
      <CadenceLine status={status} />
    </p>
  )
}

/**
 * The phase, the rate it implies, and — only when it applies — what raised it.
 *
 * The escalation note is written out rather than shown as a badge because it is the one
 * thing on this line a studio did not ask for and would be billed for. "Stepped up on
 * unusual volume" is a sentence someone can act on; a chip is something they learn to
 * ignore.
 */
function CadenceLine({ status }: { status: TitleCollectionStatus }) {
  return (
    <>
      <span className="text-ink-400">
        · {describeCadencePhase(status.cadence_phase)} · {describePollingRate(status.polls_per_day)}
      </span>
      {status.is_volume_escalated && (
        <span className="text-ink-600">· stepped up on unusual volume</span>
      )}
    </>
  )
}

/**
 * The line as it appears inside a title row, fetching its own status.
 *
 * Renders nothing at all while loading or on error. A row is not the place to report that
 * one supplementary query failed — the title itself is still correct, and an error banner
 * per row would be noise. The absence of the line is itself legible: it is what the screen
 * looked like before this story.
 */
export function TitleCollectionStatusLine({
  status,
  isPending,
}: {
  status: TitleCollectionStatus | undefined
  isPending: boolean
}) {
  if (isPending || !status) return null
  return <CollectionStatusLine status={status} />
}

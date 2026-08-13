/**
 * The pre-release / post-release boundary, client side (E02-S02).
 *
 * Mirrors `callsheet/app/core/release_phase.py` — the two have to move together, or a
 * date pushed by a week splits the server's numbers and not the chart drawn beside them.
 *
 * The phase is derived here every time it is asked for, never stored on anything. That is
 * what lets a corrected release date re-split an existing chart with nothing refetched
 * beyond the title itself.
 *
 * Dates are handled as ISO `YYYY-MM-DD` strings throughout, deliberately. Passing them
 * through `Date` would reinterpret them in the browser's timezone, and a release date is
 * a calendar day rather than an instant — parsing "2026-09-11" west of UTC yields the
 * 10th, which would move the divider by a day for half the world.
 */

export type ReleasePhase = 'pre_release' | 'post_release'

/** Release day itself is post-release: the release is the event, not the run-up to it. */
export function phaseForDate(day: string, releaseDate: string): ReleasePhase {
  return day >= releaseDate ? 'post_release' : 'pre_release'
}

export function describePhase(phase: ReleasePhase): string {
  return phase === 'post_release' ? 'Post-release' : 'Pre-release'
}

/** Formats an ISO day for display without ever constructing a `Date`. */
export function formatDay(day: string): string {
  const [year, month, dayOfMonth] = day.split('-')
  const MONTHS = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ]
  const monthLabel = MONTHS[Number(month) - 1]
  if (!monthLabel || !dayOfMonth || !year) return day
  return `${Number(dayOfMonth)} ${monthLabel} ${year}`
}

export interface TimelineMark {
  key: string
  label: string
  day: string
  phase: ReleasePhase
  kind: 'release' | 'milestone'
  /** Position along the axis, 0 to 1. */
  offsetRatio: number
}

export interface Timeline {
  start: string
  end: string
  marks: TimelineMark[]
}

const MILLISECONDS_PER_DAY = 86_400_000

/** Days between two ISO days, counted in UTC so no local offset can shift the count. */
function dayDifference(from: string, to: string): number {
  return (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / MILLISECONDS_PER_DAY
}

/**
 * Lays the release divider and every milestone marker out on a shared axis.
 *
 * This is the piece a time-series chart consumes once there is one to draw (E04/E05):
 * given the same axis bounds, the divider and the markers land in the same places they
 * do on the standalone timeline, because both come from here.
 */
export function buildTimeline(
  releaseDate: string,
  milestones: { id: string; name: string; occurs_on: string }[],
): Timeline {
  const days = [releaseDate, ...milestones.map((milestone) => milestone.occurs_on)].sort()
  const start = days[0] ?? releaseDate
  const end = days[days.length - 1] ?? releaseDate
  const span = dayDifference(start, end)

  // Every date on the same day — a title with no milestones, or all of them on release
  // day — has no axis to spread across. Everything sits at the midpoint rather than
  // dividing by zero.
  const ratioFor = (day: string) => (span === 0 ? 0.5 : dayDifference(start, day) / span)

  const marks: TimelineMark[] = [
    {
      key: 'release',
      label: 'Release',
      day: releaseDate,
      phase: 'post_release',
      kind: 'release',
      offsetRatio: ratioFor(releaseDate),
    },
    ...milestones.map((milestone) => ({
      key: milestone.id,
      label: milestone.name,
      day: milestone.occurs_on,
      phase: phaseForDate(milestone.occurs_on, releaseDate),
      kind: 'milestone' as const,
      offsetRatio: ratioFor(milestone.occurs_on),
    })),
  ]

  return { start, end, marks: marks.sort((a, b) => a.day.localeCompare(b.day)) }
}

/**
 * Turning two date inputs into the half-open instant range the API takes (E03-S03).
 *
 * Kept out of the component because every one of these conversions is a place a day can be
 * lost, and each rule below is load-bearing rather than incidental.
 *
 * **Whole days, always in UTC.** A backfill range is a pair of calendar days a studio typed,
 * not two moments. Passing `YYYY-MM-DD` through `Date` reinterprets it in the browser's
 * timezone — "2026-07-01" west of UTC becomes 30 June — which would silently shift both ends
 * of a paid-for range by a day for half the world. The same rule `lib/release-phase.ts`
 * follows, for the same reason.
 *
 * **The end is exclusive and rounds outward.** A studio picking 14 July as their last day
 * means "including the 14th", so the instant sent is midnight on the 15th. Truncating
 * instead would drop the last day of every range anyone asks for.
 *
 * **The last selectable day is yesterday.** The server refuses a range that reaches into the
 * future, and today is still being collected live — a backfill of it would pay a premium for
 * what the scheduled poll brings in for nothing, and would mark those posts as historical
 * when they are not. Overlap with live collection is harmless the other way: whatever the
 * range already holds is deduplicated on the way in.
 */

const MILLISECONDS_PER_DAY = 86_400_000

/** An ISO day offset from another, computed in UTC so no local offset can shift it. */
export function shiftDay(day: string, byDays: number): string {
  const shifted = new Date(Date.parse(`${day}T00:00:00Z`) + byDays * MILLISECONDS_PER_DAY)
  return shifted.toISOString().slice(0, 10)
}

export function todayInUtc(now: number = Date.now()): string {
  return new Date(now).toISOString().slice(0, 10)
}

/** The latest day a backfill may cover — see the note above on why it is not today. */
export function lastBackfillableDay(now: number = Date.now()): string {
  return shiftDay(todayInUtc(now), -1)
}

export function startOfDayInstant(day: string): string {
  return `${day}T00:00:00.000Z`
}

/** Midnight after `day`, which is how an inclusive last day becomes an exclusive bound. */
export function endOfDayInstant(day: string): string {
  return startOfDayInstant(shiftDay(day, 1))
}

export function isUsableRange(fromDay: string, untilDay: string, now: number = Date.now()) {
  if (!fromDay || !untilDay) return false
  if (fromDay > untilDay) return false
  return untilDay <= lastBackfillableDay(now)
}

/** Whole days covered, both ends inclusive — what the screen quotes the range as. */
export function dayCount(fromDay: string, untilDay: string): number {
  return (
    (Date.parse(`${untilDay}T00:00:00Z`) - Date.parse(`${fromDay}T00:00:00Z`)) /
      MILLISECONDS_PER_DAY +
    1
  )
}

/**
 * A sensible starting range: the earliest campaign beat that has already happened.
 *
 * The story's studio signed up "after the teaser and trailer are out", so their first
 * milestone in the past is very often the exact date they came here to type. Falling back to
 * a month covers a title whose milestones are all still ahead of it.
 */
export function defaultRangeStart(pastMilestoneDays: string[], now: number = Date.now()): string {
  const earliest = [...pastMilestoneDays].sort()[0]
  return earliest ?? shiftDay(todayInUtc(now), -30)
}

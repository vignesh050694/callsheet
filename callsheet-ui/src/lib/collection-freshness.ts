/**
 * Reading collection timestamps as a human would (E03-S01, shared with E03-S05).
 *
 * Deliberately coarse. To the minute is precise enough to answer "is this thing running",
 * and anything finer would rerender constantly to show a number nobody reads that closely.
 *
 * Extracted when collection health arrived and needed the same phrasing on the per-platform
 * lines. Two copies would drift, and the two places sit inches apart on the same screen —
 * "14h ago" beside "13 hours ago" reads as two different measurements of the same thing.
 */

import type { PlatformHealth, TitleCollectionStatus } from '@/types/api'

const MILLISECONDS_PER_MINUTE = 60_000
const MINUTES_PER_HOUR = 60
const HOURS_PER_DAY = 24

/** A rough, always-past relative time. */
export function describeElapsed(instant: string, now: number): string {
  const minutes = Math.floor((now - Date.parse(instant)) / MILLISECONDS_PER_MINUTE)
  if (!Number.isFinite(minutes)) return 'recently'
  if (minutes < 1) return 'just now'
  if (minutes < MINUTES_PER_HOUR) return `${minutes}m ago`
  const hours = Math.floor(minutes / MINUTES_PER_HOUR)
  if (hours < HOURS_PER_DAY) return `${hours}h ago`
  return `${Math.floor(hours / HOURS_PER_DAY)}d ago`
}

export function describeUpcoming(instant: string, now: number): string {
  const minutes = Math.ceil((Date.parse(instant) - now) / MILLISECONDS_PER_MINUTE)
  if (!Number.isFinite(minutes)) return 'soon'
  if (minutes <= 0) return 'due now'
  if (minutes < MINUTES_PER_HOUR) return `in ${minutes}m`
  const hours = Math.round(minutes / MINUTES_PER_HOUR)
  return hours < HOURS_PER_DAY ? `in ${hours}h` : `in ${Math.round(hours / HOURS_PER_DAY)}d`
}

/**
 * The platforms that have been asked and are not answering (E03-S05).
 *
 * The one predicate every consumer of collection health branches on, defined once. A screen
 * that computed "is this stale" for itself could disagree with the server about which
 * platforms the freshness claim excluded — and the claim is only honest because they were
 * excluded, so a disagreement there is the story's whole failure mode restored.
 */
export function stalePlatforms(status: TitleCollectionStatus): PlatformHealth[] {
  return status.platforms.filter((platform) => platform.state === 'stale')
}

export function describePlatformName(platform: string): string {
  return platform.toUpperCase()
}

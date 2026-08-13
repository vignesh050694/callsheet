/**
 * The release divider and campaign markers on a shared date axis (E02-S02).
 *
 * This is the story's visible half. A time-series chart does not exist yet — collection
 * lands in E03 and the dashboards in E04/E05 — so this renders the anchor on its own axis
 * instead. It reads its positions from `buildTimeline`, which is the same function a chart
 * will call with the same release date, so the divider lands in the same place in both.
 *
 * UI invariants: no aggregate and no mention text, so A and B do not apply. Invariant D
 * (sentiment colour budget) does: pre- and post-release are distinguished by which side of
 * the divider a marker sits on and by its label, never by hue. Saturated colour on this
 * screen would read as sentiment when it means nothing of the kind — so the divider takes
 * the brand accent as chrome, and every marker is neutral ink.
 */

import { buildTimeline, describePhase, formatDay } from '@/lib/release-phase'
import type { TitleMilestone } from '@/types/api'

interface ReleaseTimelineProps {
  releaseDate: string
  milestones: TitleMilestone[]
}

export function ReleaseTimeline({ releaseDate, milestones }: ReleaseTimelineProps) {
  const timeline = buildTimeline(releaseDate, milestones)
  const preReleaseCount = timeline.marks.filter(
    (mark) => mark.kind === 'milestone' && mark.phase === 'pre_release',
  ).length
  const postReleaseCount = timeline.marks.filter(
    (mark) => mark.kind === 'milestone' && mark.phase === 'post_release',
  ).length

  return (
    <div className="border-ink-200 rounded-lg border bg-white p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium">Campaign timeline</h2>
        <span className="text-ink-400 text-xs">
          {preReleaseCount} before release · {postReleaseCount} after
        </span>
      </div>

      <div className="relative mt-8 mb-2 h-24">
        {/* The axis. */}
        <div className="bg-ink-200 absolute top-0 right-0 left-0 h-px" />

        {timeline.marks.map((mark) => {
          const isRelease = mark.kind === 'release'
          return (
            <div
              key={mark.key}
              className="absolute top-0 flex -translate-x-1/2 flex-col items-center"
              style={{ left: `${mark.offsetRatio * 100}%` }}
            >
              <span
                className={
                  isRelease ? 'bg-brand-500 h-10 w-0.5 rounded' : 'bg-ink-400 h-5 w-px rounded'
                }
                aria-hidden="true"
              />
              <span
                className={
                  isRelease
                    ? 'text-ink-900 mt-1 text-center text-xs font-semibold whitespace-nowrap'
                    : 'text-ink-600 mt-1 max-w-24 text-center text-xs break-words'
                }
              >
                {mark.label}
              </span>
              <span className="text-ink-400 mt-0.5 text-center text-[11px] whitespace-nowrap">
                {formatDay(mark.day)}
              </span>
            </div>
          )
        })}
      </div>

      <p className="text-ink-400 mt-4 text-xs">
        Everything left of the release marker is {describePhase('pre_release').toLowerCase()};
        release day itself counts as {describePhase('post_release').toLowerCase()}, because
        first-day reaction is a response to the film rather than anticipation of it. Move the
        release date and every chart re-splits on the next read — nothing is recollected.
      </p>
    </div>
  )
}

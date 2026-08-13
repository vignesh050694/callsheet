/**
 * Per-platform collection coverage, and the warning that has to travel with the data (E03-S05).
 *
 * A studio reading a flat line on release weekend has two possible explanations and no way
 * to tell them apart: the audience went quiet, or the pipe broke. Those need opposite
 * reactions, and the expensive mistake — cutting spend on a campaign that is actually
 * working — is the one the product makes by default if it says nothing.
 *
 * Two exports, because the story asks for two different things in two different places.
 *
 * `PlatformCoverage` is the dashboard header: every platform, when it last worked, and which
 * ones are not answering.
 *
 * `StalePlatformWarning` is the piece that must sit on **every chart containing that
 * platform's data**. It is exported on its own so that the charts E05 brings can carry it
 * without reimplementing the sentence — a warning that each chart writes for itself is a
 * warning some chart will forget.
 *
 * UI invariants, checked before building:
 *
 * * **A — account-type segmentation.** No aggregate over mentions is rendered here; this
 *   describes collection attempts, not posts. The mention count it sits beside carries its
 *   own unsegmented label in `collection-status.tsx`.
 * * **B — language provenance.** No mention text, so it does not apply.
 * * **C — approval friction.** Nothing here produces an outbound action.
 * * **D — colour budget.** Greyscale, and this is the case where that rule costs something
 *   and is still right. A stale platform is the most alarming thing on the screen and the
 *   instinct is to make it red — but sentiment owns saturated colour, and a red that means
 *   "broken" here would compete with the red that means "negative" everywhere else, on the
 *   same screen. The warning is carried by an icon, weight, and an explicit sentence, which
 *   also survives greyscale export and does not rely on colour vision.
 */

import { describeElapsed, describePlatformName, stalePlatforms } from '@/lib/collection-freshness'
import type { PlatformHealth, TitleCollectionStatus } from '@/types/api'

/**
 * One platform's line: name, state, and when it last actually worked.
 *
 * The last-successful time is shown for a stale platform too, and that is the point rather
 * than a detail. "Instagram is not reporting" tells a studio something is wrong; "Instagram
 * is not reporting, last collected 14h ago" tells them how much of their release weekend has
 * a hole in it, which is the decision they are actually about to make.
 */
function PlatformLine({ platform, now }: { platform: PlatformHealth; now: number }) {
  const isStale = platform.state === 'stale'

  return (
    <li className="flex flex-wrap items-baseline justify-between gap-x-2 text-xs">
      <span className={isStale ? 'text-ink-900 font-medium' : 'text-ink-600'}>
        {isStale && (
          <span aria-hidden="true" className="mr-1">
            ⚠
          </span>
        )}
        {describePlatformName(platform.platform)}
      </span>
      <span className="text-ink-400">
        {platform.state === 'pending'
          ? 'not collected yet'
          : platform.last_successful_at
            ? `${isStale ? 'not reporting · last ' : ''}${describeElapsed(platform.last_successful_at, now)}`
            : 'never collected'}
      </span>
    </li>
  )
}

/**
 * The dashboard header's coverage block.
 *
 * `data_as_of` is rendered as a claim about the reporting platforms only, in the same
 * breath as the list of the ones excluded from it. Showing the "as of" alone would be the
 * dishonest half of the story's rule: the claim is only true because stale platforms were
 * left out of it, so the reader has to be able to see which.
 */
export function PlatformCoverage({
  status,
  now = Date.now(),
}: {
  status: TitleCollectionStatus
  now?: number
}) {
  if (status.platforms.length === 0) return null
  const stale = stalePlatforms(status)

  return (
    <div className="border-ink-200 mt-2 rounded-md border px-3 py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className="text-ink-600 text-xs font-medium">Platform coverage</span>
        <span className="text-ink-400 text-xs">
          {status.data_as_of
            ? `data as of ${describeElapsed(status.data_as_of, now)}`
            : 'no current data'}
        </span>
      </div>

      <ul className="mt-1.5 space-y-1">
        {status.platforms.map((platform) => (
          <PlatformLine key={platform.platform} platform={platform} now={now} />
        ))}
      </ul>

      {stale.length > 0 && (
        <p className="text-ink-600 mt-2 text-xs">
          The freshness above covers only the platforms still reporting.{' '}
          {stale.length === 1 ? 'One platform is' : `${stale.length} platforms are`} excluded, so
          anything counting {stale.length === 1 ? 'its' : 'their'} data is incomplete.
        </p>
      )}
    </div>
  )
}

/**
 * The warning that must accompany any chart whose data includes a stale platform.
 *
 * Renders nothing when everything is reporting, so a consumer can mount it unconditionally
 * — which is the intent. A warning a chart has to remember to add is a warning some chart
 * will not have.
 *
 * `platforms` lets a chart that only covers some platforms declare which; omitted, it warns
 * about every stale platform the title has. A chart drawing X only should not be made to
 * apologise for Instagram.
 */
export function StalePlatformWarning({
  status,
  platforms,
}: {
  status: TitleCollectionStatus
  platforms?: string[]
}) {
  const relevant = stalePlatforms(status).filter(
    (platform) => !platforms || platforms.includes(platform.platform),
  )
  if (relevant.length === 0) return null

  const names = relevant.map((platform) => describePlatformName(platform.platform)).join(', ')

  return (
    <p role="status" className="text-ink-900 mt-1 flex items-start gap-1.5 text-xs font-medium">
      <span aria-hidden="true">⚠</span>
      <span>
        {names} {relevant.length === 1 ? 'is' : 'are'} not currently reporting. This figure is
        missing {relevant.length === 1 ? 'that platform' : 'those platforms'} and is not a complete
        picture of the conversation.
      </span>
    </p>
  )
}

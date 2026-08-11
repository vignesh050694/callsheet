/**
 * Release date and campaign milestones, edited after setup (E02-S02).
 *
 * The story's "I can add milestones later without disturbing already-collected data" is
 * this screen. It saves to a schedule sub-resource that carries no identity terms, so
 * there is no path from here to the set collection is running against — a studio pushing
 * a release date by three weeks cannot accidentally rewrite what the title collects.
 *
 * The timeline above the form is the same anchor a chart will draw, rendered on its own
 * axis until there is a chart to draw it on.
 *
 * UI invariants: no aggregate, no mention text, no outbound action. Invariant D applies
 * and is handled in `ReleaseTimeline` — nothing here encodes meaning in colour.
 */

import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { MilestoneEditor } from '@/components/ui/milestone-editor'
import { ReleaseTimeline } from '@/components/ui/release-timeline'
import { ErrorState, LoadingState } from '@/components/ui/status-message'
import { useCurrentUser } from '@/hooks/use-current-user'
import { useTitle, useUpdateTitleSchedule } from '@/hooks/use-titles'
import { completedMilestones, toMilestoneDrafts, type MilestoneDraft } from '@/lib/milestones'
import { formatDay } from '@/lib/release-phase'
import type { Title } from '@/types/api'

function ScheduleForm({ title, canEdit }: { title: Title; canEdit: boolean }) {
  const navigate = useNavigate()
  const updateSchedule = useUpdateTitleSchedule(title.id)

  // Seeded once from the loaded title. Remounting on a different title is what resets it,
  // which the `key` on this component in the parent guarantees.
  const [releaseDate, setReleaseDate] = useState(title.release_date)
  const [milestones, setMilestones] = useState<MilestoneDraft[]>(() =>
    toMilestoneDrafts(title.milestones),
  )

  const hasMoved = releaseDate !== title.release_date
  const isSubmittable = Boolean(releaseDate) && canEdit && !updateSchedule.isPending

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!isSubmittable) return

    updateSchedule.mutate(
      { release_date: releaseDate, milestones: completedMilestones(milestones) },
      { onSuccess: () => void navigate('/', { replace: true }) },
    )
  }

  if (!canEdit) {
    return (
      <p className="text-ink-400 text-sm">
        Only an owner of this organization can change the release date or campaign milestones.
      </p>
    )
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="border-ink-200 space-y-4 rounded-lg border bg-white p-5"
    >
      <label className="block">
        <span className="text-ink-600 block text-xs font-medium">Release date</span>
        <input
          type="date"
          value={releaseDate}
          onChange={(event) => setReleaseDate(event.target.value)}
          required
          className="border-ink-200 focus:border-brand-500 mt-1 rounded-md border px-3 py-2 text-sm outline-none"
        />
        <span className="text-ink-400 mt-1 block text-xs">
          {hasMoved
            ? `Moving from ${formatDay(title.release_date)}. Everything already collected stays as it is — the before-and-after split is worked out when a chart is drawn, so it simply re-splits.`
            : 'The boundary every chart splits on.'}
        </span>
      </label>

      <MilestoneEditor drafts={milestones} onChange={setMilestones} />

      <button
        type="submit"
        disabled={!isSubmittable}
        className="bg-brand-500 hover:bg-brand-600 w-full rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
      >
        {updateSchedule.isPending ? 'Saving…' : 'Save schedule'}
      </button>

      {updateSchedule.isError && <ErrorState error={updateSchedule.error} />}
    </form>
  )
}

export function TitleSchedulePage() {
  const { titleId } = useParams<{ titleId: string }>()
  const currentUser = useCurrentUser()
  const title = useTitle(titleId)

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
        <h1 className="mt-2 text-xl font-semibold tracking-tight">{title.data.name}</h1>
        <p className="text-ink-600 mt-1 text-sm">Releasing {formatDay(title.data.release_date)}</p>
      </div>

      <ReleaseTimeline releaseDate={title.data.release_date} milestones={title.data.milestones} />

      <ScheduleForm key={title.data.id} title={title.data} canEdit={isOwner} />
    </section>
  )
}

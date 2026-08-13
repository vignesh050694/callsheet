/**
 * The repeatable campaign-milestone list (E02-S02).
 *
 * Shared by title setup and the schedule screen, because a beat added at setup and a beat
 * added six weeks later are the same thing — the story's requirement that milestones can
 * be added later is a routing question, not a different editor.
 *
 * Beat names are free text rather than a fixed list. Campaign shapes differ by film and by
 * industry, and a studio that cannot record "single 2 drop" records it in the name of
 * something else, which is worse than an unfamiliar label.
 */

import { completedMilestones, newMilestoneDraft, type MilestoneDraft } from '@/lib/milestones'

interface MilestoneEditorProps {
  drafts: MilestoneDraft[]
  onChange: (drafts: MilestoneDraft[]) => void
}

export function MilestoneEditor({ drafts, onChange }: MilestoneEditorProps) {
  const incompleteCount = drafts.length - completedMilestones(drafts).length

  function updateDraft(key: string, patch: Partial<MilestoneDraft>) {
    onChange(drafts.map((draft) => (draft.key === key ? { ...draft, ...patch } : draft)))
  }

  return (
    <fieldset>
      <legend className="text-ink-600 block text-xs font-medium">Campaign milestones</legend>
      <p className="text-ink-400 mt-1 text-xs">
        Optional. Teaser, trailer, audio launch, bookings open — whatever your beats are. These
        become the reference points a volume spike is explained against, so the date matters more
        than the wording.
      </p>

      {drafts.length > 0 && (
        <ul className="mt-3 space-y-2">
          {drafts.map((draft) => (
            <li key={draft.key} className="flex items-center gap-2">
              <input
                value={draft.name}
                onChange={(event) => updateDraft(draft.key, { name: event.target.value })}
                placeholder="Trailer launch"
                aria-label="Milestone name"
                className="border-ink-200 focus:border-brand-500 min-w-0 flex-1 rounded-md border px-3 py-2 text-sm outline-none"
              />
              <input
                type="date"
                value={draft.occurs_on}
                onChange={(event) => updateDraft(draft.key, { occurs_on: event.target.value })}
                aria-label="Milestone date"
                className="border-ink-200 focus:border-brand-500 shrink-0 rounded-md border px-3 py-2 text-sm outline-none"
              />
              <button
                type="button"
                onClick={() => onChange(drafts.filter((other) => other.key !== draft.key))}
                aria-label={`Remove ${draft.name || 'milestone'}`}
                className="text-ink-400 hover:text-ink-900 shrink-0 rounded-md px-2 py-2 text-sm"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        onClick={() => onChange([...drafts, newMilestoneDraft()])}
        className="border-ink-200 text-ink-600 hover:border-ink-400 mt-3 rounded-md border border-dashed px-3 py-2 text-xs font-medium"
      >
        Add a milestone
      </button>

      {incompleteCount > 0 && (
        <p className="text-ink-400 mt-2 text-xs">
          {incompleteCount === 1 ? 'One milestone needs' : `${incompleteCount} milestones need`}{' '}
          both a name and a date to be saved. Incomplete rows are ignored.
        </p>
      )}
    </fieldset>
  )
}

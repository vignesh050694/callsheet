/**
 * Draft state for the campaign-milestone editor (E02-S02).
 *
 * Separate from the component so the editor file exports only a component — Vite's fast
 * refresh gives up on a module that mixes the two.
 */

import type { TitleMilestoneInput } from '@/types/api'

export interface MilestoneDraft extends TitleMilestoneInput {
  /** Stable across reorders and deletions, so React does not reuse the wrong input. */
  key: string
}

let nextMilestoneKey = 0

export function newMilestoneDraft(): MilestoneDraft {
  nextMilestoneKey += 1
  return { key: `milestone-${nextMilestoneKey}`, name: '', occurs_on: '' }
}

export function toMilestoneDrafts(
  milestones: { name: string; occurs_on: string }[],
): MilestoneDraft[] {
  return milestones.map((milestone) => ({ ...newMilestoneDraft(), ...milestone }))
}

/** Drops the half-filled rows. A beat needs both a name and a date to be a marker. */
export function completedMilestones(drafts: MilestoneDraft[]): TitleMilestoneInput[] {
  return drafts
    .filter((draft) => draft.name.trim().length > 0 && draft.occurs_on.length > 0)
    .map((draft) => ({ name: draft.name.trim(), occurs_on: draft.occurs_on }))
}

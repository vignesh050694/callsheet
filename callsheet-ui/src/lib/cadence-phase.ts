/**
 * How a title's polling cadence reads on screen (E03-S02).
 *
 * Mirrors `callsheet/app/core/cadence_phase.py`, which is the authority on which phase a
 * title is in — the server sends the phase, this only names it. Nothing here re-derives a
 * phase from a release date, because a client that computed its own would disagree with
 * the scheduler the moment a window boundary moved on the server.
 *
 * The labels avoid the internal vocabulary. "Dormant" describes what the *system* is doing;
 * a studio eight months from release reads it as an accusation about their film. "Quiet
 * period" describes the same fact in the terms they would use.
 */

export type CadencePhase = 'dormant' | 'campaign' | 'release_surge'

const PHASE_LABELS: Record<CadencePhase, string> = {
  dormant: 'Quiet period',
  campaign: 'Campaign',
  release_surge: 'Release week',
}

export function describeCadencePhase(phase: CadencePhase): string {
  return PHASE_LABELS[phase]
}

/**
 * The rate as a studio would say it. Kept beside the label rather than behind a tooltip:
 * the phase is the *reason* and the rate is the *cost*, and someone deciding whether an
 * escalation was worth it needs both in the same glance.
 */
export function describePollingRate(pollsPerDay: number): string {
  if (pollsPerDay === 1) return 'once a day'
  return `${pollsPerDay}× a day`
}

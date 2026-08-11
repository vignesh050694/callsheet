/**
 * Who the browser is acting as.
 *
 * v1 is invite-led with no self-serve signup, so there is no login screen yet. The
 * pilot user's id is set once — from `VITE_PILOT_USER_ID` or a localStorage override —
 * and travels on every request as `X-User-Id`. This is the seam a real session layer
 * replaces; nothing else in the app reads the identity directly.
 */

const PILOT_USER_STORAGE_KEY = 'callsheet.pilotUserId'

export function getCurrentUserId(): string | null {
  const storedUserId = globalThis.localStorage?.getItem(PILOT_USER_STORAGE_KEY)
  if (storedUserId) return storedUserId

  return import.meta.env.VITE_PILOT_USER_ID ?? null
}

export function setCurrentUserId(userId: string): void {
  globalThis.localStorage?.setItem(PILOT_USER_STORAGE_KEY, userId)
}

/**
 * Decides what a signed-in user sees first (E01-S01).
 *
 * No memberships means the account has no workspace yet, which is the one condition that
 * routes to onboarding. Once an owner membership exists, the same slot renders the title
 * list. Membership comes from `/me`, so the decision is server-truth, not local state.
 *
 * An accepted artist (E01-S04) breaks the original two-way split: they hold no
 * organization membership and never will, but they are not a first-time user either.
 * Sending them to onboarding would invite them to create a production house, which is
 * the opposite of what they are here for — so titles shared with them are checked before
 * onboarding is offered.
 */

import { ErrorState, LoadingState } from '@/components/ui/status-message'
import { useCurrentUser } from '@/hooks/use-current-user'
import { useSharedTitles } from '@/hooks/use-title-invitations'
import { ApiError } from '@/lib/api-client'
import { OnboardingPage } from '@/routes/onboarding-page'
import { SharedTitlesPage } from '@/routes/shared-titles-page'
import { TitlesPage } from '@/routes/titles-page'

const UNAUTHENTICATED_STATUS = 401

function UnidentifiedCaller() {
  return (
    <div className="border-ink-200 mx-auto max-w-lg rounded-lg border bg-white px-6 py-8 text-center">
      <p className="text-sm font-medium">No pilot user configured</p>
      <p className="text-ink-600 mt-2 text-sm">
        v1 has no login screen yet. Seed a user with{' '}
        <code className="text-ink-900 font-mono text-xs">make seed-user email=… name=…</code> and
        set the printed id as{' '}
        <code className="text-ink-900 font-mono text-xs">VITE_PILOT_USER_ID</code>.
      </p>
    </div>
  )
}

export function WorkspaceGate() {
  const { data, isPending, isError, error } = useCurrentUser()
  // Fetched unconditionally so the owner/artist decision is made on one render rather
  // than flashing onboarding while a second request settles. An owner's response is an
  // empty list, which costs one cheap query.
  const sharedTitles = useSharedTitles()

  if (isPending) return <LoadingState label="Loading your workspace…" />
  if (isError) {
    if (error instanceof ApiError && error.status === UNAUTHENTICATED_STATUS) {
      return <UnidentifiedCaller />
    }
    return <ErrorState error={error} />
  }

  if (data.memberships.length > 0) return <TitlesPage />

  // Still deciding whether this is an artist or a first-time user — showing onboarding
  // here and swapping it out a moment later is the flash this guard exists to avoid.
  if (sharedTitles.isPending) return <LoadingState label="Loading your workspace…" />
  // A failed lookup is not the same as an empty one. Falling through to onboarding here
  // would invite an artist whose titles simply failed to load to create a production
  // house — the worst available guess, and one they might act on.
  if (sharedTitles.isError) return <ErrorState error={sharedTitles.error} />
  if (sharedTitles.data && sharedTitles.data.length > 0) return <SharedTitlesPage />

  return <OnboardingPage />
}

/**
 * Decides what a signed-in user sees first (E01-S01).
 *
 * No memberships means the account has no workspace yet, which is the one condition that
 * routes to onboarding. Once an owner membership exists, the same slot renders the title
 * list. Membership comes from `/me`, so the decision is server-truth, not local state.
 */

import { ErrorState, LoadingState } from '@/components/ui/status-message'
import { useCurrentUser } from '@/hooks/use-current-user'
import { ApiError } from '@/lib/api-client'
import { OnboardingPage } from '@/routes/onboarding-page'
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

  if (isPending) return <LoadingState label="Loading your workspace…" />
  if (isError) {
    if (error instanceof ApiError && error.status === UNAUTHENTICATED_STATUS) {
      return <UnidentifiedCaller />
    }
    return <ErrorState error={error} />
  }

  return data.memberships.length === 0 ? <OnboardingPage /> : <TitlesPage />
}

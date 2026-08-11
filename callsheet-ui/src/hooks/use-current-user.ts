/**
 * The signed-in user and their memberships. An empty `memberships` array is what routes
 * a first-time user to onboarding, so every screen behind the workspace gate reads it
 * from here rather than inferring org membership from a list endpoint.
 */

import { useQuery } from '@tanstack/react-query'

import { apiClient } from '@/lib/api-client'
import type { CurrentUser } from '@/types/api'

export const currentUserKeys = {
  all: ['current-user'] as const,
}

export function useCurrentUser() {
  return useQuery({
    queryKey: currentUserKeys.all,
    queryFn: ({ signal }) => apiClient.get<CurrentUser>('/me', signal),
  })
}

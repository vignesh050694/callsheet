/**
 * Data hooks for sharing a title with an agency (E01-S05). Components call these —
 * never `fetch` directly — so cache keys and invalidation stay in one file per resource.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { titleMembershipKeys } from '@/hooks/use-title-memberships'
import { apiClient } from '@/lib/api-client'
import type { AccessAuditEvent, AgencyShareCreate, TitleMembership } from '@/types/api'

export const accessLogKeys = {
  all: ['access-log'] as const,
  forTitle: (titleId: string) => [...accessLogKeys.all, titleId] as const,
}

export function useShareTitleWithAgency(titleId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: AgencyShareCreate) =>
      apiClient.post<TitleMembership>(`/titles/${titleId}/shares`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: titleMembershipKeys.forTitle(titleId ?? ''),
      })
      // The grant writes an audit row in the same transaction, so the log is stale too.
      void queryClient.invalidateQueries({ queryKey: accessLogKeys.forTitle(titleId ?? '') })
    },
  })
}

/** Owners only — the server refuses this to a shared grant, and the screen hides it. */
export function useTitleAccessLog(titleId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: accessLogKeys.forTitle(titleId ?? ''),
    queryFn: ({ signal }) =>
      apiClient.get<AccessAuditEvent[]>(`/titles/${titleId}/access-log`, signal),
    enabled: Boolean(titleId) && enabled,
  })
}

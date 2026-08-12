/**
 * Data hooks for title-scoped access (E01-S03). Components call these — never `fetch`
 * directly — so cache keys and invalidation stay in one file per resource.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '@/lib/api-client'
import type { TaggedArtistCreate, TitleMembersView, TitleMembershipCreated } from '@/types/api'

export const titleMembershipKeys = {
  all: ['title-memberships'] as const,
  forTitle: (titleId: string) => [...titleMembershipKeys.all, titleId] as const,
}

export function useTitleMemberships(titleId: string | undefined) {
  return useQuery({
    queryKey: titleMembershipKeys.forTitle(titleId ?? ''),
    queryFn: ({ signal }) =>
      apiClient.get<TitleMembersView>(`/titles/${titleId}/memberships`, signal),
    enabled: Boolean(titleId),
  })
}

export function useTagArtist(titleId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: TaggedArtistCreate) =>
      apiClient.post<TitleMembershipCreated>(`/titles/${titleId}/tagged-artists`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: titleMembershipKeys.forTitle(titleId ?? ''),
      })
    },
  })
}

export function useUntagArtist(titleId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (membershipId: string) =>
      apiClient.delete(`/titles/${titleId}/memberships/${membershipId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: titleMembershipKeys.forTitle(titleId ?? ''),
      })
    },
  })
}

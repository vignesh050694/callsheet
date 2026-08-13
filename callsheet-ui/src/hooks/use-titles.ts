/**
 * Data hooks for titles. Components call these — never `fetch` directly — so cache keys
 * and invalidation stay in one file per resource.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '@/lib/api-client'
import type { Page, Title, TitleCreate, TitleScheduleUpdate } from '@/types/api'

const DEFAULT_PAGE_SIZE = 20

export const titleKeys = {
  all: ['titles'] as const,
  forOrganization: (organizationId: string) => [...titleKeys.all, organizationId] as const,
  detail: (titleId: string) => [...titleKeys.all, 'detail', titleId] as const,
}

export function useTitles(organizationId: string | undefined, limit = DEFAULT_PAGE_SIZE) {
  return useQuery({
    queryKey: titleKeys.forOrganization(organizationId ?? ''),
    queryFn: ({ signal }) =>
      apiClient.get<Page<Title>>(
        `/organizations/${organizationId}/titles?limit=${limit}&offset=0`,
        signal,
      ),
    enabled: Boolean(organizationId),
  })
}

export function useTitle(titleId: string | undefined) {
  return useQuery({
    queryKey: titleKeys.detail(titleId ?? ''),
    queryFn: ({ signal }) => apiClient.get<Title>(`/titles/${titleId}`, signal),
    enabled: Boolean(titleId),
  })
}

export function useCreateTitle(organizationId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: TitleCreate) =>
      apiClient.post<Title>(`/organizations/${organizationId}/titles`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: titleKeys.all })
    },
  })
}

/**
 * Replaces the title's release date and milestone list.
 *
 * Invalidates every title query, not just this title's: the release date is the boundary
 * each one splits on, so a list showing "3 days to release" is stale the moment it moves.
 */
export function useUpdateTitleSchedule(titleId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: TitleScheduleUpdate) =>
      apiClient.put<Title>(`/titles/${titleId}/schedule`, payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(titleKeys.detail(updated.id), updated)
      void queryClient.invalidateQueries({ queryKey: titleKeys.all })
    },
  })
}

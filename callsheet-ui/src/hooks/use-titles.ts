/**
 * Data hooks for titles. Components call these — never `fetch` directly — so cache keys
 * and invalidation stay in one file per resource.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '@/lib/api-client'
import type { Page, Title, TitleCreate } from '@/types/api'

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

/**
 * Data hooks for organizations. Components call these — never `fetch` directly — so
 * cache keys and invalidation stay in one file per resource.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { currentUserKeys } from '@/hooks/use-current-user'
import { apiClient } from '@/lib/api-client'
import type { Organization, OrganizationCreate, Page } from '@/types/api'

const DEFAULT_PAGE_SIZE = 20

export const organizationKeys = {
  all: ['organizations'] as const,
  list: (limit: number, offset: number) =>
    [...organizationKeys.all, 'list', limit, offset] as const,
  detail: (organizationId: string) => [...organizationKeys.all, 'detail', organizationId] as const,
}

export function useOrganizations(limit = DEFAULT_PAGE_SIZE, offset = 0) {
  return useQuery({
    queryKey: organizationKeys.list(limit, offset),
    queryFn: ({ signal }) =>
      apiClient.get<Page<Organization>>(`/organizations?limit=${limit}&offset=${offset}`, signal),
  })
}

export function useOrganization(organizationId: string) {
  return useQuery({
    queryKey: organizationKeys.detail(organizationId),
    queryFn: ({ signal }) =>
      apiClient.get<Organization>(`/organizations/${organizationId}`, signal),
    enabled: Boolean(organizationId),
  })
}

export function useCreateOrganization() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: OrganizationCreate) =>
      apiClient.post<Organization>('/organizations', payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: organizationKeys.all })
      // Creating an organization also creates the caller's owner membership, which is
      // what moves them past the workspace gate.
      void queryClient.invalidateQueries({ queryKey: currentUserKeys.all })
    },
  })
}

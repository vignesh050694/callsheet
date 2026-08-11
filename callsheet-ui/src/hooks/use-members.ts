/**
 * Data hooks for the Members screen. Components call these — never `fetch` directly — so
 * cache keys and invalidation stay in one file per resource.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { currentUserKeys } from '@/hooks/use-current-user'
import { apiClient } from '@/lib/api-client'
import type { InvitationCreate, InvitationCreated, MembersView } from '@/types/api'

export const memberKeys = {
  all: ['members'] as const,
  forOrganization: (organizationId: string) => [...memberKeys.all, organizationId] as const,
}

export function useMembers(organizationId: string | undefined) {
  return useQuery({
    queryKey: memberKeys.forOrganization(organizationId ?? ''),
    queryFn: ({ signal }) =>
      apiClient.get<MembersView>(`/organizations/${organizationId}/members`, signal),
    enabled: Boolean(organizationId),
  })
}

export function useInviteMember(organizationId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: InvitationCreate) =>
      apiClient.post<InvitationCreated>(`/organizations/${organizationId}/invitations`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: memberKeys.all })
    },
  })
}

export function useResendInvitation(organizationId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (invitationId: string) =>
      apiClient.post<InvitationCreated>(`/invitations/${invitationId}/resend`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: memberKeys.forOrganization(organizationId ?? ''),
      })
    },
  })
}

export function useCancelInvitation(organizationId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (invitationId: string) => apiClient.delete(`/invitations/${invitationId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: memberKeys.forOrganization(organizationId ?? ''),
      })
    },
  })
}

export function useAcceptInvitation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (token: string) => apiClient.post<void>('/invitations/accept', { token }),
    onSuccess: () => {
      // Accepting adds a membership, which is what the workspace gate routes on.
      void queryClient.invalidateQueries({ queryKey: currentUserKeys.all })
      void queryClient.invalidateQueries({ queryKey: memberKeys.all })
    },
  })
}

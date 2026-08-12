/**
 * Data hooks for the artist's side of a title invitation (E01-S04). Components call
 * these — never `fetch` directly — so cache keys and invalidation stay in one file.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { currentUserKeys } from '@/hooks/use-current-user'
import { titleMembershipKeys } from '@/hooks/use-title-memberships'
import { apiClient } from '@/lib/api-client'
import type {
  Title,
  TitleInvitationAccept,
  TitleInvitationPreview,
  TitleMembership,
  TitleMembershipCreated,
} from '@/types/api'

export const sharedTitleKeys = {
  all: ['shared-titles'] as const,
}

export const titleInvitationKeys = {
  all: ['title-invitations'] as const,
  preview: (token: string) => [...titleInvitationKeys.all, 'preview', token] as const,
}

/**
 * The invitation behind a token.
 *
 * A query rather than a mutation even though it is a POST: previewing is read-only and
 * idempotent — the token travels in the body only to keep it out of logs and history.
 * `retry: false` because an invalid or spent token is a 404 that will not become valid
 * by asking again.
 */
export function useTitleInvitationPreview(token: string | null) {
  return useQuery({
    queryKey: titleInvitationKeys.preview(token ?? ''),
    queryFn: ({ signal }) =>
      apiClient.post<TitleInvitationPreview>('/titles/invitations/preview', { token }, signal),
    enabled: Boolean(token),
    retry: false,
  })
}

export function useAcceptTitleInvitation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: TitleInvitationAccept) =>
      apiClient.post<TitleMembership>('/titles/invitations/accept', payload),
    onSuccess: () => {
      // Accepting is what puts the title in the artist's read-only list, and the
      // workspace gate routes on both of these.
      void queryClient.invalidateQueries({ queryKey: sharedTitleKeys.all })
      void queryClient.invalidateQueries({ queryKey: currentUserKeys.all })
    },
  })
}

/** Titles shared with the signed-in user through an accepted title membership. */
export function useSharedTitles() {
  return useQuery({
    queryKey: sharedTitleKeys.all,
    queryFn: ({ signal }) => apiClient.get<Title[]>('/me/titles', signal),
  })
}

export function useResendTitleInvitation(titleId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (membershipId: string) =>
      apiClient.post<TitleMembershipCreated>(
        `/titles/${titleId}/memberships/${membershipId}/resend`,
        {},
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: titleMembershipKeys.forTitle(titleId ?? ''),
      })
    },
  })
}

/**
 * Data hooks for alias discovery (E02-S04). Components call these — never `fetch`
 * directly — so cache keys and invalidation stay in one file per resource.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { titleKeys } from '@/hooks/use-titles'
import { apiClient } from '@/lib/api-client'
import type {
  AliasApproval,
  AliasApprovalInput,
  AliasRejection,
  AliasRejectionInput,
  AliasSuggestions,
} from '@/types/api'

export const aliasSuggestionKeys = {
  all: ['alias-suggestions'] as const,
  forTitle: (titleId: string) => [...aliasSuggestionKeys.all, titleId] as const,
}

export function useAliasSuggestions(titleId: string | undefined) {
  return useQuery({
    queryKey: aliasSuggestionKeys.forTitle(titleId ?? ''),
    queryFn: ({ signal }) =>
      apiClient.get<AliasSuggestions>(`/titles/${titleId}/alias-suggestions`, signal),
    enabled: Boolean(titleId),
  })
}

/**
 * Approving writes an identity term, so the title itself is stale too — the term list,
 * `collection_terms`, and everything derived from them all move.
 */
export function useApproveAliasSuggestion(titleId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: AliasApprovalInput) =>
      apiClient.post<AliasApproval>(`/titles/${titleId}/alias-suggestions/approvals`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: aliasSuggestionKeys.forTitle(titleId ?? '') })
      void queryClient.invalidateQueries({ queryKey: titleKeys.all })
    },
  })
}

export function useRejectAliasSuggestion(titleId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: AliasRejectionInput) =>
      apiClient.post<AliasRejection>(`/titles/${titleId}/alias-suggestions/rejections`, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: aliasSuggestionKeys.forTitle(titleId ?? '') })
    },
  })
}

/** Undoes a refusal. The term becomes suggestable again if the corpus still uses it. */
export function useRestoreRejectedAlias(titleId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (rejectionId: string) =>
      apiClient.delete(`/titles/${titleId}/alias-suggestions/rejections/${rejectionId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: aliasSuggestionKeys.forTitle(titleId ?? '') })
    },
  })
}

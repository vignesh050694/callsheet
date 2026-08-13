/**
 * Data hooks for the mentions feed and exclusion rules (E02-S05). Components call these —
 * never `fetch` directly — so cache keys and invalidation stay in one file per resource.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { collectionKeys } from '@/hooks/use-collection-status'
import { titleKeys } from '@/hooks/use-titles'
import { apiClient } from '@/lib/api-client'
import type {
  Exclusion,
  ExclusionCreated,
  ExclusionImpact,
  ExclusionInput,
  ExclusionRemoved,
  MentionFeed,
} from '@/types/api'

export const mentionKeys = {
  all: ['mentions'] as const,
  feed: (titleId: string, includeExcluded: boolean) =>
    [...mentionKeys.all, titleId, { includeExcluded }] as const,
}

export const exclusionKeys = {
  all: ['exclusions'] as const,
  forTitle: (titleId: string) => [...exclusionKeys.all, titleId] as const,
}

export function useMentionFeed(titleId: string | undefined, includeExcluded: boolean) {
  return useQuery({
    queryKey: mentionKeys.feed(titleId ?? '', includeExcluded),
    queryFn: ({ signal }) =>
      apiClient.get<MentionFeed>(
        `/titles/${titleId}/mentions?include_excluded=${includeExcluded}`,
        signal,
      ),
    enabled: Boolean(titleId),
  })
}

export function useTitleExclusions(titleId: string | undefined) {
  return useQuery({
    queryKey: exclusionKeys.forTitle(titleId ?? ''),
    queryFn: ({ signal }) => apiClient.get<Exclusion[]>(`/titles/${titleId}/exclusions`, signal),
    enabled: Boolean(titleId),
  })
}

/**
 * Measures a rule before it exists. A mutation rather than a query because it is a POST
 * with a body and it is run on demand — but it writes nothing, and the rule does not exist
 * until `useCreateExclusion` creates it.
 */
export function useMeasureExclusionImpact(titleId: string | undefined) {
  return useMutation({
    mutationFn: (payload: ExclusionInput) =>
      apiClient.post<ExclusionImpact>(`/titles/${titleId}/exclusions/impact`, payload),
  })
}

/**
 * Invalidates the feed, the exclusion list, the title, and the collection status — the
 * mention count on every one of them just moved, and a screen still showing the old
 * number is the thing the confirmation step exists to prevent.
 */
function useExclusionInvalidation(titleId: string | undefined) {
  const queryClient = useQueryClient()

  return () => {
    void queryClient.invalidateQueries({ queryKey: mentionKeys.all })
    void queryClient.invalidateQueries({ queryKey: exclusionKeys.forTitle(titleId ?? '') })
    void queryClient.invalidateQueries({ queryKey: titleKeys.all })
    void queryClient.invalidateQueries({ queryKey: collectionKeys.all })
  }
}

export function useCreateExclusion(titleId: string | undefined) {
  const invalidate = useExclusionInvalidation(titleId)

  return useMutation({
    mutationFn: (payload: ExclusionInput) =>
      apiClient.post<ExclusionCreated>(`/titles/${titleId}/exclusions`, payload),
    onSuccess: invalidate,
  })
}

export function useRemoveExclusion(titleId: string | undefined) {
  const invalidate = useExclusionInvalidation(titleId)

  return useMutation({
    mutationFn: (termId: string) =>
      apiClient.delete<ExclusionRemoved>(`/titles/${titleId}/exclusions/${termId}`),
    onSuccess: invalidate,
  })
}

/**
 * Data hooks for historical backfill (E03-S03).
 *
 * Three calls in the order the screen uses them: quote a range, confirm it, watch it.
 *
 * The quote is a mutation rather than a query even though it changes nothing on the server.
 * It is keyed by two dates a studio is still typing, and as a query it would either refetch
 * on every keystroke or need debouncing bolted on top of a cache key that is never reused.
 * As a mutation it runs exactly when the range is submitted for pricing, which is also the
 * moment the story requires it: before the confirm, never after.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiClient } from '@/lib/api-client'
import type { Backfill, BackfillEstimate, BackfillRangeRequest, Page } from '@/types/api'

const HISTORY_PAGE_SIZE = 10
const PENDING_REFETCH_INTERVAL_MS = 5_000

export const backfillKeys = {
  all: ['backfills'] as const,
  forTitle: (titleId: string) => [...backfillKeys.all, titleId] as const,
}

export function useBackfillEstimate(titleId: string | undefined) {
  return useMutation({
    mutationFn: (range: BackfillRangeRequest) =>
      apiClient.post<BackfillEstimate>(`/titles/${titleId}/backfills/estimate`, range),
  })
}

/**
 * This title's backfill history, polled while any of it is still running.
 *
 * A backfill is minutes of work started by a button press, so the screen a studio is left
 * looking at has to fill itself in. Once nothing is pending the answer cannot change on its
 * own and the polling stops.
 */
export function useBackfills(titleId: string | undefined) {
  return useQuery({
    queryKey: backfillKeys.forTitle(titleId ?? ''),
    queryFn: ({ signal }) =>
      apiClient.get<Page<Backfill>>(
        `/titles/${titleId}/backfills?limit=${HISTORY_PAGE_SIZE}&offset=0`,
        signal,
      ),
    enabled: Boolean(titleId),
    staleTime: 0,
    refetchInterval: (query) => {
      const items = query.state.data?.items
      if (!items) return false
      const isAnyPending = items.some(
        (backfill) => backfill.status === 'queued' || backfill.status === 'running',
      )
      return isAnyPending ? PENDING_REFETCH_INTERVAL_MS : false
    },
  })
}

/**
 * Confirms a backfill at the quoted ceiling.
 *
 * Invalidates the title's collection status as well as its backfill list: the mention count
 * on the titles list is about to move by however much history lands, and a studio who just
 * paid for six weeks of conversation should not have to reload to see it.
 */
export function useRequestBackfill(titleId: string | undefined) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (range: BackfillRangeRequest) =>
      apiClient.post<Backfill>(`/titles/${titleId}/backfills`, range),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: backfillKeys.all })
      void queryClient.invalidateQueries({ queryKey: ['collection'] })
    },
  })
}

/**
 * Collection status for one title (E03-S01).
 *
 * Polled rather than fetched once, because this is the one query on the screen whose
 * answer changes without the user doing anything — the whole point of the state it shows
 * is that a studio can watch an empty title fill in. The interval is deliberately far
 * shorter than the collection cadence: it costs one cheap local request and it is what
 * turns "wait and refresh" into "watch it happen".
 *
 * Polling stops once the title has mentions and is not stalled. At that point the answer
 * only moves once every couple of hours, and a tab left open overnight should not spend
 * the night asking.
 */

import { useQuery } from '@tanstack/react-query'

import { apiClient } from '@/lib/api-client'
import type { TitleCollectionStatus } from '@/types/api'

const AWAITING_REFETCH_INTERVAL_MS = 15_000

export const collectionKeys = {
  all: ['collection'] as const,
  forTitle: (titleId: string) => [...collectionKeys.all, 'status', titleId] as const,
}

export function useCollectionStatus(titleId: string | undefined) {
  return useQuery({
    queryKey: collectionKeys.forTitle(titleId ?? ''),
    queryFn: ({ signal }) =>
      apiClient.get<TitleCollectionStatus>(`/titles/${titleId}/collection`, signal),
    enabled: Boolean(titleId),
    // Zero, so the freshness line is never a stale render of a moving value.
    staleTime: 0,
    refetchInterval: (query) => {
      const status = query.state.data
      if (!status) return false
      // A stalled title stops polling even while it has no mentions. Nothing is queued,
      // so the answer cannot change on its own — asking again every fifteen seconds
      // forever would be a request that can only ever return the same thing, and the
      // screen already tells the reader it needs a human.
      if (status.is_stalled) return false
      return status.is_awaiting_first_results ? AWAITING_REFETCH_INTERVAL_MS : false
    },
  })
}

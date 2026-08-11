/**
 * The setup preview (E02-S03).
 *
 * A mutation rather than a query, even though it reads: it costs real money upstream, so
 * it must run when the owner asks and never on mount, refocus, or retry. TanStack Query
 * retries failed *queries* by default — a retried preview is a second paid call for a
 * sample nobody asked twice for — and mutations do not retry.
 */

import { useMutation } from '@tanstack/react-query'

import { apiClient } from '@/lib/api-client'
import type { TitlePreview, TitlePreviewRequest } from '@/types/api'

export function useTitlePreview(organizationId: string | undefined) {
  return useMutation({
    mutationFn: (payload: TitlePreviewRequest) =>
      apiClient.post<TitlePreview>(`/organizations/${organizationId}/title-previews`, payload),
  })
}

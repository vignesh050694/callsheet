import { useQuery } from '@tanstack/react-query'

import { apiClient } from '@/lib/api-client'
import type { HealthResponse } from '@/types/api'

const HEALTH_POLL_INTERVAL_MS = 30_000

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => apiClient.get<HealthResponse>('/health', signal),
    refetchInterval: HEALTH_POLL_INTERVAL_MS,
  })
}

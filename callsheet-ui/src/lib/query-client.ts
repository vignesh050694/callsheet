import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/lib/api-client'

const STALE_TIME_MS = 30_000
const MAX_RETRIES = 2
const CLIENT_ERROR_STATUS_THRESHOLD = 400
const SERVER_ERROR_STATUS_THRESHOLD = 500

/** Retrying a 4xx just repeats a request the server already rejected on its merits. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (
    error instanceof ApiError &&
    error.status >= CLIENT_ERROR_STATUS_THRESHOLD &&
    error.status < SERVER_ERROR_STATUS_THRESHOLD
  ) {
    return false
  }
  return failureCount < MAX_RETRIES
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: STALE_TIME_MS,
      refetchOnWindowFocus: false,
      retry: shouldRetry,
    },
    mutations: {
      retry: false,
    },
  },
})

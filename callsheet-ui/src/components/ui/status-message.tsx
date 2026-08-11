import type { ReactNode } from 'react'

import { ApiError } from '@/lib/api-client'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return <p className="text-ink-400 py-8 text-sm">{label}</p>
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="border-ink-200 rounded-lg border border-dashed px-6 py-10 text-center">
      <p className="text-ink-400 text-sm">{children}</p>
    </div>
  )
}

export function ErrorState({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : 'Something went wrong'
  const requestId = error instanceof ApiError ? error.requestId : null

  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3">
      <p className="text-sm font-medium text-red-800">{message}</p>
      {requestId && <p className="mt-1 font-mono text-xs text-red-600">request {requestId}</p>}
    </div>
  )
}

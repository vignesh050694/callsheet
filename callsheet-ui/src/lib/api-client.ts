/**
 * Thin fetch wrapper around the Callsheet API.
 *
 * Every call goes through here so error shape, JSON handling, and the base URL live in
 * one place. The backend returns `{ code, message, request_id }` on failure — `ApiError`
 * carries all three so a screen can show the message and log the request id.
 */

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'
const NO_CONTENT_STATUS = 204

export interface ApiErrorBody {
  code: string
  message: string
  request_id?: string | null
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.requestId = body.request_id ?? null
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

async function readErrorBody(response: Response): Promise<ApiErrorBody> {
  try {
    const parsed = (await response.json()) as Partial<ApiErrorBody> & { detail?: unknown }
    if (typeof parsed.code === 'string' && typeof parsed.message === 'string') {
      return parsed as ApiErrorBody
    }
    // FastAPI's own validation errors use `detail` rather than our envelope.
    return {
      code: 'ValidationError',
      message: JSON.stringify(parsed.detail ?? parsed),
    }
  } catch {
    return { code: 'UnknownError', message: response.statusText || 'Request failed' }
  }
}

export async function request<TResponse>(
  path: string,
  { method = 'GET', body, signal }: RequestOptions = {},
): Promise<TResponse> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    signal,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorBody(response))
  }

  if (response.status === NO_CONTENT_STATUS) {
    return undefined as TResponse
  }

  return (await response.json()) as TResponse
}

export const apiClient = {
  get: <TResponse>(path: string, signal?: AbortSignal) =>
    request<TResponse>(path, { method: 'GET', signal }),
  post: <TResponse>(path: string, body: unknown) =>
    request<TResponse>(path, { method: 'POST', body }),
  patch: <TResponse>(path: string, body: unknown) =>
    request<TResponse>(path, { method: 'PATCH', body }),
  delete: (path: string) => request<void>(path, { method: 'DELETE' }),
}

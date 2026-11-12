/**
 * API client for the FIG backend.
 *
 * Every response is either { data, meta } or { error }.
 * Never read `data` without checking `ok` — the backend will not return a bare payload.
 */

export interface ApiMeta {
  request_id: string
  generated_at: string
  next_cursor?: string | null
  truncated?: boolean
  [key: string]: unknown
}

export interface ApiErrorBody {
  code: string
  message: string
  details: Record<string, unknown>
  request_id: string
}

export interface ApiEnvelope<T> {
  data: T
  meta: ApiMeta
}

export class ApiError extends Error {
  readonly code: string
  readonly details: Record<string, unknown>
  readonly requestId: string
  readonly status: number

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.details = body.details ?? {}
    this.requestId = body.request_id
  }
}

const BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<ApiEnvelope<T>> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })

  const text = await res.text()
  const body: unknown = text ? JSON.parse(text) : {}

  if (!res.ok) {
    const err = (body as { error?: ApiErrorBody }).error
    if (err) throw new ApiError(res.status, err)
    throw new ApiError(res.status, {
      code: 'INTERNAL_ERROR',
      message: `HTTP ${res.status}`,
      details: {},
      request_id: '',
    })
  }

  return body as ApiEnvelope<T>
}

export interface HealthPayload {
  status: string
  version: string
  env: string
}

export interface ReadyPayload {
  status: string
  version: string
  checks: Record<string, { ok: boolean; error: string | null }>
}

export const api = {
  health: () => request<HealthPayload>('/health'),
  ready: () => request<ReadyPayload>('/ready'),
}

export { request }

/**
 * Thin HTTP client for the DPRK CTI API. Deliberately kept small —
 * under ~100 lines — so the eventual OpenAPI → Zod codegen migration
 * (deferred per plan D7 to PR #13+) can replace the per-endpoint
 * functions in `./api/endpoints.ts` without touching the transport
 * layer.
 *
 * What this module provides
 * -------------------------
 * 1. `ApiError` — a typed `Error` subclass carrying the HTTP status +
 *    parsed `detail` body. All non-2xx responses surface as `ApiError`.
 *    Handlers branch on `err.status`; never string-match the message.
 * 2. `apiGet<T>(path, schema)` — GET + Zod runtime validation. Returns
 *    the narrowed schema output; a schema mismatch (contract drift)
 *    throws synchronously with Zod's error detail.
 * 3. `apiPost<T>(path, body, schema?)` — POST JSON body, optionally
 *    validating the response. `schema=null` (explicit) for 204-style
 *    endpoints.
 *
 * What this module does NOT do
 * ----------------------------
 * - No retry / backoff. Consumers (React Query) own retry policy.
 * - No auth header injection. The backend identifies users via the
 *   signed session cookie; `credentials: "include"` carries it on
 *   every same-origin and permitted cross-origin request.
 * - No global error handling. Callers (route boundaries, component
 *   error states) decide how errors render.
 * - No URL building for query parameters. Callers pre-assemble the
 *   path. (A typed URL builder is codegen's problem — see D7.)
 */

import type { ZodType } from 'zod'

import { config } from '../config'

export class ApiError extends Error {
  public readonly status: number
  public readonly detail: unknown

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `API error ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

type FetchOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

/**
 * Low-level fetch wrapper. Normalizes non-2xx responses into
 * `ApiError`. Returns the raw `Response` on success; callers decide
 * whether to `.json()` it (many do; 204 handlers do not).
 */
async function apiFetch(path: string, opts: FetchOptions = {}): Promise<Response> {
  const { method = 'GET', body, signal } = opts
  const url = `${config.apiUrl}${path}`

  const headers: HeadersInit = {}
  const init: RequestInit = {
    method,
    credentials: 'include',
    signal,
    headers,
  }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  const res = await fetch(url, init)
  if (!res.ok) {
    // Try to parse the error body as JSON. If the server returned a
    // plain text error or an empty body, fall back to null — callers
    // still get a typed `ApiError` with the status, which is what
    // the branching logic needs.
    let detail: unknown = null
    try {
      detail = await res.json()
    } catch {
      // non-JSON body — accept as null detail
    }
    throw new ApiError(res.status, detail)
  }
  return res
}

/**
 * GET + Zod-validated response. Use for every typed read endpoint.
 * A parse failure throws ZodError synchronously; route-level error
 * boundaries surface this as contract drift, which is the correct
 * posture for a runtime schema mismatch.
 */
export async function apiGet<T>(
  path: string,
  schema: ZodType<T>,
  signal?: AbortSignal,
): Promise<T> {
  const res = await apiFetch(path, { signal })
  const json = (await res.json()) as unknown
  return schema.parse(json)
}

/**
 * POST JSON body. `schema=null` explicitly signals a no-response
 * endpoint (204). `schema=undefined` is a programming error — use
 * `null` to be explicit, otherwise supply a Zod schema.
 */
export async function apiPost<T>(
  path: string,
  body: unknown,
  schema: ZodType<T>,
  signal?: AbortSignal,
): Promise<T>
export async function apiPost(
  path: string,
  body: unknown,
  schema: null,
  signal?: AbortSignal,
): Promise<null>
export async function apiPost<T>(
  path: string,
  body: unknown,
  schema: ZodType<T> | null,
  signal?: AbortSignal,
): Promise<T | null> {
  const res = await apiFetch(path, { method: 'POST', body, signal })
  if (schema === null) return null
  const json = (await res.json()) as unknown
  return schema.parse(json)
}

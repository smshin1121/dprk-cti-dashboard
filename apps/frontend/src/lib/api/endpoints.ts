/**
 * Per-endpoint functions. Thin wrappers over `apiGet` / `apiPost`
 * tied to a concrete BE route and Zod schema. This is the layer
 * the OpenAPI → Zod codegen (plan D7 defer) will eventually replace.
 *
 * Keeping this file small + obvious + one-function-per-endpoint
 * makes the codegen replacement a mechanical find-and-replace when
 * it lands.
 */

import { apiGet, apiPost } from '../api'
import { currentUserSchema, type CurrentUser } from './schemas'

/** `GET /api/v1/auth/me` — returns the current authenticated user. */
export function getMe(signal?: AbortSignal): Promise<CurrentUser> {
  return apiGet('/api/v1/auth/me', currentUserSchema, signal)
}

/**
 * `POST /api/v1/auth/logout` — 204 No Content.
 *
 * `schema=null` is explicit (see `apiPost` overload) — the BE has no
 * response body. Caller mutation (`useLogout`) ignores the resolved
 * value and operates on React Query cache invalidation instead.
 */
export function logout(signal?: AbortSignal): Promise<null> {
  return apiPost('/api/v1/auth/logout', undefined, null, signal)
}

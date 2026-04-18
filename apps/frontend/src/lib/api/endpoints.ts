/**
 * Per-endpoint functions. Thin wrappers over `apiGet` / `apiPost`
 * tied to a concrete BE route and Zod schema. This is the layer
 * the OpenAPI → Zod codegen (plan D7 defer) will eventually replace.
 *
 * Keeping this file small + obvious + one-function-per-endpoint
 * makes the codegen replacement a mechanical find-and-replace when
 * it lands.
 */

import { apiGet, apiPost, apiRawGet } from '../api'
import {
  type DashboardSummaryFilters,
  toDashboardSummaryQueryParams,
} from '../dashboardFilters'
import {
  type ActorListPagination,
  type IncidentListFilters,
  type ReportListFilters,
  toActorListQueryParams,
  toIncidentListQueryParams,
  toReportListQueryParams,
} from '../listFilters'
import {
  actorListResponseSchema,
  currentUserSchema,
  dashboardSummarySchema,
  type ActorListResponse,
  type CurrentUser,
  type DashboardSummary,
  type IncidentListResponse,
  type ReportListResponse,
} from './schemas'

/** `GET /api/v1/auth/me` — returns the current authenticated user. */
export function getMe(signal?: AbortSignal): Promise<CurrentUser> {
  return apiGet('/api/v1/auth/me', currentUserSchema, signal)
}

/**
 * `GET /api/v1/dashboard/summary` — D6 aggregate shape.
 *
 * Filter contract: accepts the wire-shaped `DashboardSummaryFilters`
 * (the same object that seeds the React Query cache key). The type
 * has no tlp field by construction (plan D5), so this endpoint is
 * structurally incapable of leaking a tlp query param even if a
 * future caller tries. `toDashboardSummaryQueryParams` handles the
 * `group_id` repetition + date-key serialization.
 */
export function getDashboardSummary(
  filters: DashboardSummaryFilters,
  signal?: AbortSignal,
): Promise<DashboardSummary> {
  const qs = toDashboardSummaryQueryParams(filters).toString()
  const path = qs.length > 0
    ? `/api/v1/dashboard/summary?${qs}`
    : '/api/v1/dashboard/summary'
  return apiGet(path, dashboardSummarySchema, signal)
}

/**
 * `GET /api/v1/actors` — offset-paginated. Plan D7 Zod-validated.
 *
 * No filter contract — actors endpoint ignores dateFrom/dateTo/
 * groupIds/tlp entirely. The `ActorListPagination` argument shape is
 * narrow (`limit` + `offset` only) so a future edit trying to pass
 * FilterBar state is a compile error, not a silently-ignored query
 * param.
 */
export function listActors(
  pagination: ActorListPagination = {},
  signal?: AbortSignal,
): Promise<ActorListResponse> {
  const qs = toActorListQueryParams(pagination).toString()
  const path = qs.length > 0
    ? `/api/v1/actors?${qs}`
    : '/api/v1/actors'
  return apiGet(path, actorListResponseSchema, signal)
}

/**
 * `GET /api/v1/reports` — keyset-paginated. Plan D7 types-only (no
 * runtime Zod). See `ReportListResponse` / `ReportItem` docstrings.
 *
 * Filter input type `ReportListFilters` has no group/tlp fields so
 * the FilterBar's group+TLP state cannot reach the wire; tests
 * `listFilters.test.ts` pin the runtime equivalence as a belt.
 */
export async function listReports(
  filters: ReportListFilters,
  pagination: { cursor?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<ReportListResponse> {
  const qs = toReportListQueryParams(filters, pagination).toString()
  const path = qs.length > 0
    ? `/api/v1/reports?${qs}`
    : '/api/v1/reports'
  // Types-only — apiRawGet skips the Zod parse step. Safe within
  // PR #12 scope: shell-level table renders only the documented
  // fields; unexpected extras are ignored.
  return apiRawGet<ReportListResponse>(path, signal)
}

/**
 * `GET /api/v1/incidents` — keyset-paginated. Plan D7 types-only.
 */
export async function listIncidents(
  filters: IncidentListFilters,
  pagination: { cursor?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<IncidentListResponse> {
  const qs = toIncidentListQueryParams(filters, pagination).toString()
  const path = qs.length > 0
    ? `/api/v1/incidents?${qs}`
    : '/api/v1/incidents'
  return apiRawGet<IncidentListResponse>(path, signal)
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

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
  type AnalyticsFilters,
  type AttackMatrixOptions,
  toAttackMatrixQueryParams,
  toGeoQueryParams,
  toTrendQueryParams,
} from '../analyticsFilters'
import {
  type DashboardSummaryFilters,
  toDashboardSummaryQueryParams,
} from '../dashboardFilters'
import {
  type ActorListPagination,
  type ActorReportsFilters,
  type IncidentListFilters,
  type ReportListFilters,
  type SearchFilters,
  toActorListQueryParams,
  toActorReportsQueryParams,
  toIncidentListQueryParams,
  toReportListQueryParams,
  toSearchQueryParams,
} from '../listFilters'
import {
  actorDetailSchema,
  actorListResponseSchema,
  actorReportsResponseSchema,
  attackMatrixResponseSchema,
  currentUserSchema,
  dashboardSummarySchema,
  geoResponseSchema,
  incidentDetailSchema,
  reportDetailSchema,
  searchResponseSchema,
  similarReportsResponseSchema,
  SIMILAR_K_DEFAULT,
  trendResponseSchema,
  type ActorDetail,
  type ActorListResponse,
  type AttackMatrixResponse,
  type CurrentUser,
  type DashboardSummary,
  type GeoResponse,
  type IncidentDetail,
  type IncidentListResponse,
  type ReportDetail,
  type ReportListResponse,
  type SearchResponse,
  type SimilarReportsResponse,
  type TrendResponse,
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
 * `GET /api/v1/analytics/attack_matrix` — plan D2 row-based matrix.
 *
 * Shared filter contract with /dashboard/summary (date_from/date_to/
 * group_id[]). `top_n` is attack-matrix-only; BE bounds `[1, 200]`
 * with default 30 when omitted. `AnalyticsFilters` type has no tlp
 * field by construction — a future edit cannot leak TLP to this wire.
 */
export function getAttackMatrix(
  filters: AnalyticsFilters,
  options: AttackMatrixOptions = {},
  signal?: AbortSignal,
): Promise<AttackMatrixResponse> {
  const qs = toAttackMatrixQueryParams(filters, options).toString()
  const path = qs.length > 0
    ? `/api/v1/analytics/attack_matrix?${qs}`
    : '/api/v1/analytics/attack_matrix'
  return apiGet(path, attackMatrixResponseSchema, signal)
}

/**
 * `GET /api/v1/analytics/trend` — monthly report-volume buckets.
 * Zero-count months are omitted by the BE; the FE viz owns gap-fill.
 */
export function getTrend(
  filters: AnalyticsFilters,
  signal?: AbortSignal,
): Promise<TrendResponse> {
  const qs = toTrendQueryParams(filters).toString()
  const path = qs.length > 0
    ? `/api/v1/analytics/trend?${qs}`
    : '/api/v1/analytics/trend'
  return apiGet(path, trendResponseSchema, signal)
}

/**
 * `GET /api/v1/analytics/geo` — country-aggregated incident count.
 *
 * BE accepts `group_id[]` but treats it as a no-op (schema has no
 * incident→group path). We still serialize it so a future BE lock
 * wiring the filter would not require a FE change.
 */
export function getGeo(
  filters: AnalyticsFilters,
  signal?: AbortSignal,
): Promise<GeoResponse> {
  const qs = toGeoQueryParams(filters).toString()
  const path = qs.length > 0
    ? `/api/v1/analytics/geo?${qs}`
    : '/api/v1/analytics/geo'
  return apiGet(path, geoResponseSchema, signal)
}

/**
 * `GET /api/v1/reports/{id}` — plan D1 + D9 + D11 (PR #14 Group D).
 *
 * Path-param only; no filter querystring. Detail pages aren't
 * filterable — the id IS the identifier. Caller guards `id` before
 * calling (the hook layer enables the query only for positive
 * integer ids); `apiGet` surfaces 404 as `ApiError`.
 */
export function getReportDetail(
  id: number,
  signal?: AbortSignal,
): Promise<ReportDetail> {
  return apiGet(`/api/v1/reports/${id}`, reportDetailSchema, signal)
}

/**
 * `GET /api/v1/incidents/{id}` — plan D1 + D9 + D11 (PR #14 Group D).
 */
export function getIncidentDetail(
  id: number,
  signal?: AbortSignal,
): Promise<IncidentDetail> {
  return apiGet(`/api/v1/incidents/${id}`, incidentDetailSchema, signal)
}

/**
 * `GET /api/v1/actors/{id}` — plan D1 + D11 (PR #14 Group D).
 *
 * Response schema has no reports-like key per D11; unknown keys are
 * silently stripped (see `actorDetailSchema` docstring).
 */
export function getActorDetail(
  id: number,
  signal?: AbortSignal,
): Promise<ActorDetail> {
  return apiGet(`/api/v1/actors/${id}`, actorDetailSchema, signal)
}

/**
 * `GET /api/v1/actors/{id}/reports` — PR #15 Phase 3 slice 2 Group D
 * (plan D1 + D2 + D9 + D15).
 *
 * Keyset-paginated — reuses `ReportListResponse` envelope (plan D9
 * lock, `actorReportsResponseSchema` is a reference-identical alias).
 * Filter surface is date range + cursor + limit only (plan D2); no
 * `q` / `tag` / `source` / `tlp` reach this wire because the
 * `ActorReportsFilters` type has no such fields.
 *
 * The `actorId` lives in the URL path (not the query string). 404 on
 * unknown actor surfaces as `ApiError` via `apiGet`; the hook layer
 * guards `actorId > 0` before calling so we never fire a 404-prone
 * request on mount for a missing path param.
 *
 * Empty branches (plan D15 b/c/d) return 200 + `{items: [],
 * next_cursor: null}` which parses cleanly through the schema.
 */
export function getActorReports(
  actorId: number,
  filters: ActorReportsFilters = {},
  pagination: { cursor?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<ReportListResponse> {
  const qs = toActorReportsQueryParams(filters, pagination).toString()
  const path = qs.length > 0
    ? `/api/v1/actors/${actorId}/reports?${qs}`
    : `/api/v1/actors/${actorId}/reports`
  return apiGet(path, actorReportsResponseSchema, signal)
}

/**
 * `GET /api/v1/reports/{id}/similar?k=N` — plan D2 + D8 + D10
 * (PR #14 Group D).
 *
 * `k` is caller-configurable (not global state); it participates in
 * the BE Redis cache key `similar_reports:{id}:{k}` AND in the FE
 * React Query cache key — changing k opens a fresh cache scope on
 * both sides. Defaults to `SIMILAR_K_DEFAULT` (10) matching BE.
 * Caller is responsible for keeping `k` in `[SIMILAR_K_MIN,
 * SIMILAR_K_MAX]`; out-of-range values surface as BE 422.
 */
export function getSimilarReports(
  reportId: number,
  k: number = SIMILAR_K_DEFAULT,
  signal?: AbortSignal,
): Promise<SimilarReportsResponse> {
  const path = `/api/v1/reports/${reportId}/similar?k=${k}`
  return apiGet(path, similarReportsResponseSchema, signal)
}

/**
 * `GET /api/v1/search` — PR #17 Phase 3 slice 3 Group D (plan D8 +
 * D9 + D13).
 *
 * FTS-only MVP this slice. `q` is required and non-empty — the hook
 * layer gates on `q.trim().length > 0` before invoking this function
 * (blank queries would return 422 from the BE). Filter surface is
 * `{date_from, date_to, limit}` by plan D8; `toSearchQueryParams`
 * enforces that whitelist at runtime.
 *
 * Response is the `SearchResponse` envelope — per-hit `fts_rank` is
 * a float, `vector_rank` is literally `null` this slice (D9 forward-
 * compat slot; memory `pattern_fts_first_hybrid_mvp`). No pagination
 * cursor — the endpoint returns at most `limit` rows in one shot.
 */
export function getSearchHits(
  q: string,
  filters: SearchFilters = {},
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const qs = toSearchQueryParams(q, filters).toString()
  return apiGet(`/api/v1/search?${qs}`, searchResponseSchema, signal)
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

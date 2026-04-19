/**
 * List-endpoint filter transforms. Counterparts to
 * `dashboardFilters.ts` for `/reports` + `/incidents`.
 *
 * BE wire surface per endpoint (see
 * `services/api/src/api/routers/{reports,incidents}.py`):
 *
 *  - `/reports`:   q, tag[], source[], date_from, date_to, cursor, limit
 *  - `/incidents`: date_from, date_to, motivation[], sector[],
 *                  country[], cursor, limit
 *
 * PR #12 scope (plan §4 Group F): shell-level only. We emit
 * `date_from` / `date_to` from the shared FilterBar. Tag / source /
 * motivation / sector / country / q all defer to PR #13 when the
 * advanced filter surface lands per design doc §14 Phase 2 W3+.
 *
 * Absent from every list transform by design:
 *
 *  - `groupIds` — the FilterBar's group selection is only consumed
 *    by `/dashboard/summary` (which scopes `top_groups`). NONE of
 *    the three list endpoints accepts a `group_id[]` param. If a
 *    future edit tries to append one, the BE silently drops the
 *    unknown query param (FastAPI default for un-declared kwargs)
 *    AND the URL + React Query cache key pointlessly expand. The
 *    `ReportListFilters` / `IncidentListFilters` types have no
 *    group field, so leaking is a compile error. Tests pin the
 *    equivalence at runtime as a defensive belt.
 *
 *  - `tlpLevels` — same UI-only rationale as the dashboard. D5 lock.
 *
 * Actors has NO filter surface at all — pagination-only (plan D5 +
 * D3). We still expose a typed `ActorListPagination` object so the
 * `useActorsList` hook's argument shape stays uniform with the
 * other two hooks for onboarding clarity.
 */

import type { FilterState } from '../stores/filters'

export interface ReportListFilters {
  date_from?: string
  date_to?: string
}

export interface IncidentListFilters {
  date_from?: string
  date_to?: string
}

export interface ActorListPagination {
  limit?: number
  offset?: number
}

/**
 * `/api/v1/actors/{id}/reports` — PR #15 Phase 3 slice 2 Group D
 * (plan D2). Filter surface is MINIMAL: date range only. No `q` /
 * `tag` / `source` / `tlp` / `groupIds` — reusing any of those types
 * would pollute the React Query cache key with fields the BE
 * ignores. Pinned at the type level + runtime serializer below.
 *
 * Kept as a distinct type (not a `ReportListFilters` alias) so a
 * future widening of `/reports` filter scope cannot accidentally
 * leak into this endpoint's wire contract.
 */
export interface ActorReportsFilters {
  date_from?: string
  date_to?: string
}

function pickDateRange(
  state: Pick<FilterState, 'dateFrom' | 'dateTo'>,
): { date_from?: string; date_to?: string } {
  const out: { date_from?: string; date_to?: string } = {}
  if (state.dateFrom != null) out.date_from = state.dateFrom
  if (state.dateTo != null) out.date_to = state.dateTo
  return out
}

export function toReportListFilters(
  state: Pick<FilterState, 'dateFrom' | 'dateTo'>,
): ReportListFilters {
  return pickDateRange(state)
}

export function toIncidentListFilters(
  state: Pick<FilterState, 'dateFrom' | 'dateTo'>,
): IncidentListFilters {
  return pickDateRange(state)
}

export function toReportListQueryParams(
  filters: ReportListFilters,
  pagination: { cursor?: string; limit?: number } = {},
): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.date_from != null) params.append('date_from', filters.date_from)
  if (filters.date_to != null) params.append('date_to', filters.date_to)
  if (pagination.cursor != null) params.append('cursor', pagination.cursor)
  if (pagination.limit != null) params.append('limit', String(pagination.limit))
  return params
}

export function toIncidentListQueryParams(
  filters: IncidentListFilters,
  pagination: { cursor?: string; limit?: number } = {},
): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.date_from != null) params.append('date_from', filters.date_from)
  if (filters.date_to != null) params.append('date_to', filters.date_to)
  if (pagination.cursor != null) params.append('cursor', pagination.cursor)
  if (pagination.limit != null) params.append('limit', String(pagination.limit))
  return params
}

export function toActorListQueryParams(
  pagination: ActorListPagination,
): URLSearchParams {
  const params = new URLSearchParams()
  if (pagination.limit != null) params.append('limit', String(pagination.limit))
  if (pagination.offset != null) params.append('offset', String(pagination.offset))
  return params
}

/**
 * `/api/v1/actors/{id}/reports` — PR #15 Group D. Mirror of
 * `toReportListQueryParams` except the path prefix is different —
 * the `actorId` lives in the URL path (not the query string) so the
 * serializer here emits only `date_from` / `date_to` / `cursor` /
 * `limit`. Keeps tlp / groupIds / q / tag / source structurally out
 * of reach.
 */
export function toActorReportsFilters(
  state: Pick<FilterState, 'dateFrom' | 'dateTo'>,
): ActorReportsFilters {
  return pickDateRange(state)
}

export function toActorReportsQueryParams(
  filters: ActorReportsFilters,
  pagination: { cursor?: string; limit?: number } = {},
): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.date_from != null) params.append('date_from', filters.date_from)
  if (filters.date_to != null) params.append('date_to', filters.date_to)
  if (pagination.cursor != null) params.append('cursor', pagination.cursor)
  if (pagination.limit != null) params.append('limit', String(pagination.limit))
  return params
}

/**
 * `/api/v1/search` — PR #17 Phase 3 slice 3 Group D (plan D8 + D13).
 *
 * Filter surface is MINIMAL by plan D8: date range + `limit` only.
 * No cursor (`/search` is NOT keyset-paginated this slice), no
 * `tag` / `source` / `tlp` / `groupIds` / nested `q`-subfilters —
 * the `q` string lives outside this type so it can be debounced
 * independently and so React Query cache key construction keeps
 * the typed (`SearchFilters`) and non-typed (`q`) inputs distinct.
 *
 * Kept as a distinct type (not an `ActorReportsFilters` alias) so a
 * future widening of either endpoint's filter scope cannot
 * accidentally leak into the other's wire contract. Pinned by
 * `listFilters.test.ts::toSearchQueryParams`.
 */
export interface SearchFilters {
  date_from?: string
  date_to?: string
  limit?: number
}

/**
 * Derive a `SearchFilters` from the filter store's date range. Mirror
 * of `toActorReportsFilters` / `toReportListFilters` — date range only.
 * Intentionally ignores `tlp` / `groupIds` / `q` on the FilterState so
 * toggling those in the global FilterBar cannot leak into this
 * endpoint's query-string or its React Query cache scope.
 */
export function toSearchFilters(
  state: Pick<FilterState, 'dateFrom' | 'dateTo'>,
): SearchFilters {
  return pickDateRange(state)
}

/**
 * Serialize a `/api/v1/search` request into `URLSearchParams`. The
 * required `q` is appended first; the three optional filter keys
 * (`date_from` / `date_to` / `limit`) follow. No other params ever
 * surface — the type signature makes the whitelist enforcement
 * structural, and the implementation below duplicates it at runtime
 * as a defense-in-depth layer pinned by `listFilters.test.ts`.
 */
export function toSearchQueryParams(
  q: string,
  filters: SearchFilters = {},
): URLSearchParams {
  const params = new URLSearchParams()
  params.append('q', q)
  if (filters.date_from != null) params.append('date_from', filters.date_from)
  if (filters.date_to != null) params.append('date_to', filters.date_to)
  if (filters.limit != null) params.append('limit', String(filters.limit))
  return params
}

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

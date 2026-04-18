/**
 * Pure transforms from the UI filter store to dashboard-summary
 * BE wire shape. Two layers:
 *
 *   `toDashboardSummaryFilters(state)` — store (FilterState) →
 *     `DashboardSummaryFilters` (the typed object that flows to
 *     React Query as part of the cache key AND as the source for the
 *     URL params). Drops null date ends and empty group lists so the
 *     query string and cache key stay clean.
 *
 *   `toDashboardSummaryQueryParams(filters)` — `DashboardSummaryFilters`
 *     → `URLSearchParams`. Emits `group_id` as a repeated param
 *     matching the BE router (`services/api/.../dashboard.py` —
 *     `Annotated[list[int] | None, Query()]`).
 *
 * D5 lock — TLP isolation:
 * `DashboardSummaryFilters` has NO tlp field. The transform is the
 * single chokepoint where TLP can be excluded; the type system makes
 * future drift a compile error rather than a runtime regression.
 * Tests in `dashboardFilters.test.ts` pin the equivalence at runtime.
 */

import type { FilterState } from '../stores/filters'

/** Wire-shaped filter object — mirrors BE `/dashboard/summary` query
 *  param names. Used as the React Query key payload AND as the input
 *  to `toDashboardSummaryQueryParams`. */
export interface DashboardSummaryFilters {
  /** ISO yyyy-mm-dd. Omitted when no lower bound. */
  date_from?: string
  /** ISO yyyy-mm-dd. Omitted when no upper bound. */
  date_to?: string
  /** Repeatable group_id param. Omitted when no group filter. */
  group_id?: number[]
}

export function toDashboardSummaryFilters(
  state: Pick<FilterState, 'dateFrom' | 'dateTo' | 'groupIds'>,
): DashboardSummaryFilters {
  const filters: DashboardSummaryFilters = {}
  if (state.dateFrom != null) filters.date_from = state.dateFrom
  if (state.dateTo != null) filters.date_to = state.dateTo
  if (state.groupIds.length > 0) filters.group_id = [...state.groupIds]
  return filters
}

export function toDashboardSummaryQueryParams(
  filters: DashboardSummaryFilters,
): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.date_from != null) params.append('date_from', filters.date_from)
  if (filters.date_to != null) params.append('date_to', filters.date_to)
  if (filters.group_id != null) {
    for (const id of filters.group_id) params.append('group_id', String(id))
  }
  return params
}

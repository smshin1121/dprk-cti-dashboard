/**
 * Pure transforms from the UI filter store to `/api/v1/analytics/*`
 * BE wire shape. Mirror of `dashboardFilters.ts` — same filter
 * contract (plan D2 + D9 in PR #13), so the canonicalization rules
 * carry over:
 *
 *   - `tlpLevels` is NEVER serialized here (D4 lock; UI-only).
 *   - `groupIds` is sorted numerically ascending so equivalent sets
 *     toggled in different orders produce identical cache keys +
 *     URLs. The store keeps insertion order for its UI rationale;
 *     canonicalization happens at the server-state boundary.
 *   - Empty / null fields are dropped from the emitted object +
 *     URLSearchParams, keeping cache keys and URL strings minimal.
 *
 * Two layers per endpoint:
 *
 *   `toAnalyticsFilters(state)` — store → `AnalyticsFilters` (shared
 *     across the 3 endpoints because they accept the same wire
 *     contract).
 *
 *   `toAttackMatrixQueryParams(filters, options)` /
 *   `toTrendQueryParams(filters)` /
 *   `toGeoQueryParams(filters)` — `AnalyticsFilters` (+ options)
 *     → `URLSearchParams`. attack_matrix additionally emits `top_n`
 *     when set; the BE bounds it to `[1, 200]` with default 30.
 *
 * The shared `AnalyticsFilters` type mirrors `DashboardSummaryFilters`
 * structurally. Kept as a distinct type to keep endpoints
 * independent — a future BE lock that diverges (e.g., add a filter
 * only attack_matrix accepts) is then a local edit to this file, not
 * a cascade through `dashboardFilters.ts`.
 */

import type { FilterState } from '../stores/filters'

/** Wire-shaped filter object — mirrors BE `/analytics/*` query param
 *  names. Used as the React Query key payload AND as input to the
 *  per-endpoint query-string serializers. No tlp field by
 *  construction (plan D4 + carried PR #12 D5 lock). */
export interface AnalyticsFilters {
  /** ISO yyyy-mm-dd. Omitted when no lower bound. */
  date_from?: string
  /** ISO yyyy-mm-dd. Omitted when no upper bound. */
  date_to?: string
  /** Repeatable group_id param. Omitted when no group filter. */
  group_id?: number[]
}

/** Attack-matrix-only option. BE bounds top_n to [1, 200] (default 30
 *  at the router layer). Kept optional so callers can omit and
 *  inherit the BE default. */
export interface AttackMatrixOptions {
  top_n?: number
}

/** Actor-network options — three independent per-kind caps. BE bounds
 *  each to [1, 200] with default 25 at the router layer. Kept optional
 *  so callers can omit and inherit the BE defaults; each option that
 *  IS set is serialized + included in the query key (per-instance
 *  caching scope, mirrors the AttackMatrixOptions pattern). Plan
 *  ``docs/plans/actor-network-data.md`` v1.6 §4 T9. */
export interface ActorNetworkOptions {
  top_n_actor?: number
  top_n_tool?: number
  top_n_sector?: number
}

export function toAnalyticsFilters(
  state: Pick<FilterState, 'dateFrom' | 'dateTo' | 'groupIds'>,
): AnalyticsFilters {
  const filters: AnalyticsFilters = {}
  if (state.dateFrom != null) filters.date_from = state.dateFrom
  if (state.dateTo != null) filters.date_to = state.dateTo
  if (state.groupIds.length > 0) {
    // Ascending numeric sort — same rule as dashboardFilters. Without
    // this, [1,3] and [3,1] would hash to distinct React Query keys
    // and URLs for the same logical filter (Codex R1 P2 in PR #12).
    filters.group_id = [...state.groupIds].sort((a, b) => a - b)
  }
  return filters
}

function appendCore(
  params: URLSearchParams,
  filters: AnalyticsFilters,
): void {
  if (filters.date_from != null) params.append('date_from', filters.date_from)
  if (filters.date_to != null) params.append('date_to', filters.date_to)
  if (filters.group_id != null) {
    for (const id of filters.group_id) params.append('group_id', String(id))
  }
}

export function toAttackMatrixQueryParams(
  filters: AnalyticsFilters,
  options: AttackMatrixOptions = {},
): URLSearchParams {
  const params = new URLSearchParams()
  appendCore(params, filters)
  if (options.top_n != null) params.append('top_n', String(options.top_n))
  return params
}

export function toTrendQueryParams(
  filters: AnalyticsFilters,
): URLSearchParams {
  const params = new URLSearchParams()
  appendCore(params, filters)
  return params
}

export function toGeoQueryParams(
  filters: AnalyticsFilters,
): URLSearchParams {
  const params = new URLSearchParams()
  appendCore(params, filters)
  return params
}

export function toActorNetworkQueryParams(
  filters: AnalyticsFilters,
  options: ActorNetworkOptions = {},
): URLSearchParams {
  const params = new URLSearchParams()
  appendCore(params, filters)
  // Each per-kind cap is independently optional; only emit the param
  // when the caller set it so the BE default applies otherwise.
  if (options.top_n_actor != null)
    params.append('top_n_actor', String(options.top_n_actor))
  if (options.top_n_tool != null)
    params.append('top_n_tool', String(options.top_n_tool))
  if (options.top_n_sector != null)
    params.append('top_n_sector', String(options.top_n_sector))
  return params
}

/**
 * `/api/v1/analytics/incidents_trend` — PR #23 §6.A C1 endpoint.
 *
 * `group_by` is REQUIRED (no flat mode — that lives on `/trend`).
 * Type pinned at `'motivation' | 'sector'` so a typo never reaches
 * the BE Literal validator (which would surface as a 422 in the
 * happy path). The FE shape is the same shared `AnalyticsFilters`
 * (date_from / date_to / group_id[]) the other analytics endpoints
 * accept; group_id is documented BE-side as a no-op for this
 * endpoint but the param is still serialized for surface symmetry.
 */
export type IncidentsTrendGroupBy = 'motivation' | 'sector'

export function toIncidentsTrendQueryParams(
  filters: AnalyticsFilters,
  groupBy: IncidentsTrendGroupBy,
): URLSearchParams {
  const params = new URLSearchParams()
  appendCore(params, filters)
  params.append('group_by', groupBy)
  return params
}

/**
 * `/api/v1/analytics/correlation` — Phase 3 Slice 3 D-1 (PR-B T3).
 *
 * Wire surface differs from the shared `AnalyticsFilters` family — this
 * endpoint takes opaque series IDs (`x` / `y`, both required) plus an
 * optional date window plus an `alpha` significance threshold; there is
 * no `group_id` repetition at all. Hence a dedicated builder rather
 * than reuse of `appendCore`.
 *
 * `dateFrom` / `dateTo` are nullable — `null` means "let the BE resolve
 * from the data window" (`resolve_default_date_window` server-side); the
 * BE echoes the resolved dates back in the 200 response. The query key
 * (T4) keeps the user-input `null` literal so empty-date URL state is
 * stable across renders (per CONTRACT.md §1 / umbrella §7.5 line 576).
 *
 * `alpha` is always emitted — the BE Redis cache key includes it
 * (`correlation:v1:{x}:{y}:{date_from}:{date_to}:{alpha}`); the FE hook
 * supplies the literal `0.05` until UX surfaces it (umbrella §10.1 / Q4
 * default; CONTRACT.md §1 hook signature).
 */
export function toCorrelationQueryParams(
  x: string,
  y: string,
  dateFrom: string | null,
  dateTo: string | null,
  alpha: number,
): URLSearchParams {
  const params = new URLSearchParams()
  params.append('x', x)
  params.append('y', y)
  if (dateFrom != null) params.append('date_from', dateFrom)
  if (dateTo != null) params.append('date_to', dateTo)
  params.append('alpha', String(alpha))
  return params
}

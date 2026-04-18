/**
 * React Query key factory. Centralizing key construction means:
 *
 * - Rename a key in ONE place when the BE route renames
 * - Easy grep — `queryKeys.me()` surfaces every consumer
 * - Stable keys: identical filter input → structurally equal key so
 *   React Query's shallow cache lookup hits the same entry
 *
 * Future groups append to this file:
 * - Group F: `actors(pagination)`, `reports(filters, cursor)`, etc.
 *
 * D5 lock — cache-key TLP isolation:
 * `dashboardSummary(filters)` takes `DashboardSummaryFilters` whose
 * type carries no tlp field. Toggling TLP in the UI MUST NOT
 * invalidate the dashboard cache; the single way to satisfy that is
 * to never put TLP in the key in the first place. Enforced at the
 * type boundary + pinned by `queryKeys.test.ts`.
 */

import type { DashboardSummaryFilters } from './dashboardFilters'
import type {
  ActorListPagination,
  IncidentListFilters,
  ReportListFilters,
} from './listFilters'

export const queryKeys = {
  me: () => ['me'] as const,
  dashboardSummary: (filters: DashboardSummaryFilters) =>
    ['dashboard', 'summary', filters] as const,

  /**
   * `/api/v1/actors` — pagination-only. No FilterBar input reaches
   * this key: the `ActorListPagination` type has no filter fields.
   */
  actors: (pagination: ActorListPagination) =>
    ['actors', pagination] as const,

  /**
   * `/api/v1/reports` + `/api/v1/incidents` — date-range filters +
   * cursor. `ReportListFilters` / `IncidentListFilters` have no
   * group/tlp fields, so TLP + group changes can NEVER invalidate
   * these caches. Pinned in `listFilters.test.ts`.
   */
  reports: (
    filters: ReportListFilters,
    pagination: { cursor?: string; limit?: number } = {},
  ) => ['reports', filters, pagination] as const,

  incidents: (
    filters: IncidentListFilters,
    pagination: { cursor?: string; limit?: number } = {},
  ) => ['incidents', filters, pagination] as const,
} as const

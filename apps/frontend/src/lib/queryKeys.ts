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

export const queryKeys = {
  me: () => ['me'] as const,
  dashboardSummary: (filters: DashboardSummaryFilters) =>
    ['dashboard', 'summary', filters] as const,
} as const

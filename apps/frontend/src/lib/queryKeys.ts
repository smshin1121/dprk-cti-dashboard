/**
 * React Query key factory. Centralizing key construction means:
 *
 * - Rename a key in ONE place when the BE route renames
 * - Easy grep — `queryKeys.me()` surfaces every consumer
 * - Stable keys: `queryKeys.dashboardSummary(filters)` returns the
 *   same array reference shape for identical filter inputs, so
 *   React Query's referential equality cache lookup works
 *
 * Future groups append to this file:
 * - Group E: `dashboardSummary(filters)`
 * - Group F: `actors(pagination)`, `reports(filters, cursor)`, etc.
 */

export const queryKeys = {
  me: () => ['me'] as const,
} as const

/**
 * `/api/v1/actors/{id}/reports` React Query hook — PR #15 Phase 3
 * slice 2 Group D (plan D1 + D2 + D13).
 *
 * Subscription discipline (same pattern as `useSimilarReports`):
 *
 *   No FilterBar state (no `useFilterStore` selector). Cache scope
 *   is exactly `(actorId, filters, pagination)` where `filters` is
 *   the date-range-only `ActorReportsFilters` and `pagination` is
 *   `{cursor?, limit?}`. FilterBar TLP or group toggles MUST NOT
 *   refetch this query; pinned by `useActorReports.test.tsx`.
 *
 * Enable guard: `Number.isInteger(actorId) && actorId > 0`. The
 * page-level caller (`ActorDetailPage` via `parseDetailId`) already
 * gates on this; the hook pin is a defense-in-depth layer so a
 * future caller that forgets the parser still never fires a
 * 404-prone request on mount.
 *
 * D15 empty-branch handling lives in the schema layer —
 * `actorReportsResponseSchema` parses `{items: [], next_cursor:
 * null}` as a valid 200 response. The consuming panel renders an
 * empty-state card; this hook does not inject fake/heuristic
 * fallback rows.
 *
 * Refetch policy: `staleTime: 30_000` matches the detail hooks;
 * the report→actor link set doesn't churn faster than the actor
 * detail itself does.
 */

import { useQuery } from '@tanstack/react-query'

import { getActorReports } from '../../lib/api/endpoints'
import type { ReportListResponse } from '../../lib/api/schemas'
import type { ActorReportsFilters } from '../../lib/listFilters'
import { queryKeys } from '../../lib/queryKeys'

export function useActorReports(
  actorId: number,
  filters: ActorReportsFilters = {},
  pagination: { cursor?: string; limit?: number } = {},
) {
  return useQuery<ReportListResponse>({
    queryKey: queryKeys.actorReports(actorId, filters, pagination),
    queryFn: ({ signal }) =>
      getActorReports(actorId, filters, pagination, signal),
    enabled: Number.isInteger(actorId) && actorId > 0,
    staleTime: 30_000,
  })
}

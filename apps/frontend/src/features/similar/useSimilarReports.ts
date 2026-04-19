/**
 * `/api/v1/reports/{id}/similar?k=N` React Query hook — PR #14
 * Group D (plan D2 + D8 + D10).
 *
 * Subscription discipline:
 *   No FilterBar state. Cache scope is exactly `(reportId, k)` —
 *   same shape as the BE Redis key `similar_reports:{id}:{k}`, so
 *   BE and FE cache partitions line up 1:1. FilterBar date /
 *   group / tlp toggles MUST NOT refetch this; pinned by
 *   `useSimilarReports.test.tsx`.
 *
 * `k` is caller-configurable (mirrors `useAttackMatrix`'s `top_n`
 * pattern). Defaults to `SIMILAR_K_DEFAULT` (10). The k bounds
 * `[SIMILAR_K_MIN, SIMILAR_K_MAX]` are enforced at the BE router;
 * out-of-range values surface as 422 errors through React Query's
 * `isError`.
 *
 * Enable guard: `Number.isInteger(reportId) && reportId > 0`.
 *
 * D10 empty-contract handling lives in the schema layer —
 * `similarReportsResponseSchema` parses `{items: []}` as a valid
 * 200 response. The consuming panel renders an empty-state card;
 * this hook does not inject any fake/heuristic fallback.
 *
 * Refetch policy: `staleTime: 30_000` matches the detail hooks;
 * similarity results don't change faster than the source report
 * does.
 */

import { useQuery } from '@tanstack/react-query'

import { getSimilarReports } from '../../lib/api/endpoints'
import {
  SIMILAR_K_DEFAULT,
  type SimilarReportsResponse,
} from '../../lib/api/schemas'
import { queryKeys } from '../../lib/queryKeys'

export function useSimilarReports(
  reportId: number,
  k: number = SIMILAR_K_DEFAULT,
) {
  return useQuery<SimilarReportsResponse>({
    queryKey: queryKeys.similarReports(reportId, k),
    queryFn: ({ signal }) => getSimilarReports(reportId, k, signal),
    enabled: Number.isInteger(reportId) && reportId > 0,
    staleTime: 30_000,
  })
}

/**
 * `/api/v1/analytics/correlation` React Query hook — Phase 3 Slice 3
 * D-1 (PR-B T5).
 *
 * Subscription discipline:
 *   No `useFilterStore` subscription. Correlation has its own page-
 *   local URL-state namespace (B5: `x`, `y`, `date_from`, `date_to`,
 *   `method`) hydrated by `useFilterUrlSync` into page state — NOT
 *   into the global filter store. The hook takes the 4 wire-relevant
 *   inputs (`x`, `y`, `dateFrom`, `dateTo`) plus `alpha` as positional
 *   args, mirroring `useSimilarReports(reportId, k)`.
 *
 * Cache scope:
 *   Tuple `(x, y, dateFrom, dateTo, alpha)` — isomorphic to the BE
 *   Redis cache key `correlation:v1:{x}:{y}:{date_from}:{date_to}:{alpha}`
 *   (umbrella §7.5 line 576). `null` dates preserve the literal `null`
 *   in the key so the empty-date URL state is stable across renders
 *   per CONTRACT.md §1. `method` (Pearson/Spearman) is purely visual —
 *   the chart toggles between two views of the same response, so it
 *   does NOT participate in the key (T4 lock + this hook's
 *   `pattern_shared_query_cache_multi_subscriber` invariant pinned by
 *   the T7 method-toggle test).
 *
 * Refetch policy:
 *   `staleTime: 300_000` (5 min) — umbrella NFR-1 + §8.7. Correlation
 *   is a heavier statistical primitive than KPI summary (`staleTime:
 *   30_000` on `useDashboardSummary`); 5 min matches the BE Redis TTL
 *   so FE and BE caches expire together. Per plan §B3 rationale.
 *
 * Enable guard:
 *   Both series IDs must be non-empty. `x === y` is intentionally NOT
 *   guarded — the BE returns 422 `value_error.identical_series` and
 *   the typed surface flows through `getCorrelation`'s envelope-parse
 *   path so B10 can render the typed-reason copy. Catching x===y
 *   client-side would short-circuit the B10 typed path and force a
 *   second handler.
 *
 * 422 surface: `getCorrelation` parses the thrown `ApiError.detail`
 * through `correlationErrorEnvelopeSchema` (T3) so consumers get the
 * typed shape on `query.error.detail`. B10 narrows on
 * `detail[0].type` to one of the four router-authored constants;
 * envelope drift falls through to "Unable to load data" copy.
 */

import { useQuery } from '@tanstack/react-query'

import { getCorrelation } from '../../../lib/api/endpoints'
import type { CorrelationResponse } from '../../../lib/api/schemas'
import { queryKeys } from '../../../lib/queryKeys'

export function useCorrelation(
  x: string,
  y: string,
  dateFrom: string | null,
  dateTo: string | null,
  alpha: number,
) {
  return useQuery<CorrelationResponse>({
    queryKey: queryKeys.analyticsCorrelation(x, y, dateFrom, dateTo, alpha),
    queryFn: ({ signal }) =>
      getCorrelation(x, y, dateFrom, dateTo, alpha, signal),
    enabled: x.length > 0 && y.length > 0,
    staleTime: 300_000,
  })
}

/**
 * `/api/v1/analytics/correlation/series` React Query hook —
 * Phase 3 Slice 3 D-1 (PR-B T5).
 *
 * Catalog endpoint. Plan §B3 + umbrella §8.7 lock:
 *   `staleTime: Infinity` — the catalog is small (≈ 20 series IDs at
 *   spec time) and immutable per session; a single fetch on first
 *   subscriber serves every consumer for the rest of the session.
 *   Pinned by `pattern_shared_query_cache_multi_subscriber` —
 *   `CorrelationFilters` (X dropdown), `CorrelationFilters` (Y
 *   dropdown), and `CorrelationLagChart` caption (resolves series IDs
 *   to display labels) all subscribe to the same hook → one fetch
 *   total.
 *
 * No FilterBar subscription. The catalog has no query params; RBAC
 * matrix gates the endpoint at the BE. FilterBar date / group / tlp
 * toggles cannot reach this cache slot — there's no input surface
 * for them to enter.
 *
 * Errors surface immediately (no `retry`) for B8 (a) error-state
 * render — a failing catalog fetch blocks the page from picking
 * defaults, which is the correct UX (no chart without legend).
 */

import { useQuery } from '@tanstack/react-query'

import { getCorrelationCatalog } from '../../../lib/api/endpoints'
import type { CorrelationCatalogResponse } from '../../../lib/api/schemas'
import { queryKeys } from '../../../lib/queryKeys'

export function useCorrelationSeries() {
  return useQuery<CorrelationCatalogResponse>({
    queryKey: queryKeys.analyticsCorrelationCatalog(),
    queryFn: ({ signal }) => getCorrelationCatalog(signal),
    staleTime: Infinity,
  })
}

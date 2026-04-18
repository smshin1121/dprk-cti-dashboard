/**
 * `/api/v1/dashboard/summary` React Query hook.
 *
 * Subscription discipline (plan D5 + D10):
 * We intentionally subscribe to the BE-relevant fields only —
 * `dateFrom`, `dateTo`, `groupIds`. TLP lives in the same store
 * but is UI-only, so this hook MUST NOT re-run when the user
 * toggles a TLP checkbox. Three selectors picking primitives
 * (and one stable array reference) is the cleanest way to guarantee
 * that; `useShallow` on a derived object won't help because the
 * group_id array inside the transformed payload is a fresh
 * reference every render (it's sorted + spread).
 *
 * Referential stability:
 * `useMemo` over the three BE fields produces a stable
 * `DashboardSummaryFilters` object that's structurally equal
 * across renders when inputs are unchanged. React Query also does
 * its own structural comparison on the queryKey, so even an
 * unstable key wouldn't cause refetch — but a stable filters
 * object removes spurious re-invocations of the queryFn and keeps
 * devtools readable.
 *
 * Refetch policy:
 * `staleTime: 30_000` — a KPI aggregate rarely changes faster than
 * every 30s in this system; shorter windows just burn rate-limit
 * budget during analyst panning. `retry: false` inherits from the
 * QueryClient default; 4xx from the BE should surface immediately
 * so the FE can render the D11 inline error card, not backoff
 * silently.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { getDashboardSummary } from '../../lib/api/endpoints'
import {
  type DashboardSummaryFilters,
  toDashboardSummaryFilters,
} from '../../lib/dashboardFilters'
import type { DashboardSummary } from '../../lib/api/schemas'
import { queryKeys } from '../../lib/queryKeys'
import { useFilterStore } from '../../stores/filters'

export function useDashboardSummary() {
  // Primitive selectors — skip the TLP subscription entirely so its
  // changes don't fire this hook's render cycle (D5 lock).
  const dateFrom = useFilterStore((s) => s.dateFrom)
  const dateTo = useFilterStore((s) => s.dateTo)
  const groupIds = useFilterStore((s) => s.groupIds)

  // The transform only needs dateFrom/dateTo/groupIds — its Pick<>
  // signature excludes tlpLevels by construction, which is why this
  // subscription never has to touch TLP state (D5 lock at the type
  // layer, not just at runtime).
  const filters: DashboardSummaryFilters = useMemo(
    () => toDashboardSummaryFilters({ dateFrom, dateTo, groupIds }),
    [dateFrom, dateTo, groupIds],
  )

  return useQuery<DashboardSummary>({
    queryKey: queryKeys.dashboardSummary(filters),
    queryFn: ({ signal }) => getDashboardSummary(filters, signal),
    staleTime: 30_000,
  })
}

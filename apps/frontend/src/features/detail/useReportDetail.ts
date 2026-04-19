/**
 * `/api/v1/reports/{id}` React Query hook — PR #14 Group D.
 *
 * Subscription discipline (plan D1 + D11):
 *   This hook subscribes to NO FilterBar state. The detail page isn't
 *   filterable — the path-param `id` IS the identifier. Toggling
 *   FilterBar dates / groups / TLP MUST NOT invalidate or refetch
 *   this cache; enforcement is structural (no `useFilterStore`
 *   import) and pinned by `useReportDetail.test.tsx`.
 *
 * Enable guard: `Number.isInteger(id) && id > 0`. The router
 * (Group E) parses the URL param and passes an invalid sentinel
 * when the segment is malformed — the hook stays disabled and the
 * page renders NotFound / error state instead.
 *
 * Refetch policy: `staleTime: 30_000` mirrors the analytics hooks.
 * Detail payloads don't churn minute-to-minute; a 30s cache avoids
 * jitter when a user navigates back-and-forth between detail pages.
 */

import { useQuery } from '@tanstack/react-query'

import { getReportDetail } from '../../lib/api/endpoints'
import type { ReportDetail } from '../../lib/api/schemas'
import { queryKeys } from '../../lib/queryKeys'

export function useReportDetail(id: number) {
  return useQuery<ReportDetail>({
    queryKey: queryKeys.reportDetail(id),
    queryFn: ({ signal }) => getReportDetail(id, signal),
    enabled: Number.isInteger(id) && id > 0,
    staleTime: 30_000,
  })
}

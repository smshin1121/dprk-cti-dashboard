/**
 * `/api/v1/reports` list hook — keyset pagination, date-range filter.
 *
 * Filter subscription: `dateFrom` + `dateTo` only. TLP + groupIds are
 * not read here. The transform `toReportListFilters` has no fields
 * to carry either — the type system + hook subscription boundary
 * together make TLP / group leakage structurally impossible.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { listReports } from '../../lib/api/endpoints'
import type { ReportListResponse } from '../../lib/api/schemas'
import {
  toReportListFilters,
  type ReportListFilters,
} from '../../lib/listFilters'
import { queryKeys } from '../../lib/queryKeys'
import { useFilterStore } from '../../stores/filters'

export interface UseReportsListArgs {
  cursor?: string
  limit?: number
}

export function useReportsList(args: UseReportsListArgs = {}) {
  const dateFrom = useFilterStore((s) => s.dateFrom)
  const dateTo = useFilterStore((s) => s.dateTo)

  const filters: ReportListFilters = useMemo(
    () => toReportListFilters({ dateFrom, dateTo }),
    [dateFrom, dateTo],
  )

  const pagination = useMemo(
    () => ({ cursor: args.cursor, limit: args.limit }),
    [args.cursor, args.limit],
  )

  return useQuery<ReportListResponse>({
    queryKey: queryKeys.reports(filters, pagination),
    queryFn: ({ signal }) => listReports(filters, pagination, signal),
    staleTime: 30_000,
  })
}

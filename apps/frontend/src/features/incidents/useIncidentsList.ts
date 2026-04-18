/**
 * `/api/v1/incidents` list hook — keyset pagination, date-range filter.
 *
 * Same subscription discipline as `useReportsList`: dateFrom + dateTo
 * only. Motivation / sector / country filter surfaces defer to PR
 * #13; for PR #12 shell scope the BE returns an unfiltered page
 * through the date range.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { listIncidents } from '../../lib/api/endpoints'
import type { IncidentListResponse } from '../../lib/api/schemas'
import {
  toIncidentListFilters,
  type IncidentListFilters,
} from '../../lib/listFilters'
import { queryKeys } from '../../lib/queryKeys'
import { useFilterStore } from '../../stores/filters'

export interface UseIncidentsListArgs {
  cursor?: string
  limit?: number
}

export function useIncidentsList(args: UseIncidentsListArgs = {}) {
  const dateFrom = useFilterStore((s) => s.dateFrom)
  const dateTo = useFilterStore((s) => s.dateTo)

  const filters: IncidentListFilters = useMemo(
    () => toIncidentListFilters({ dateFrom, dateTo }),
    [dateFrom, dateTo],
  )

  const pagination = useMemo(
    () => ({ cursor: args.cursor, limit: args.limit }),
    [args.cursor, args.limit],
  )

  return useQuery<IncidentListResponse>({
    queryKey: queryKeys.incidents(filters, pagination),
    queryFn: ({ signal }) => listIncidents(filters, pagination, signal),
    staleTime: 30_000,
  })
}

/**
 * `/api/v1/incidents/{id}` React Query hook — PR #14 Group D.
 *
 * Same subscription + enable discipline as `useReportDetail` (see
 * that file's docstring for the full rationale). The path-param id
 * IS the identifier; no FilterBar state participates.
 */

import { useQuery } from '@tanstack/react-query'

import { getIncidentDetail } from '../../lib/api/endpoints'
import type { IncidentDetail } from '../../lib/api/schemas'
import { queryKeys } from '../../lib/queryKeys'

export function useIncidentDetail(id: number) {
  return useQuery<IncidentDetail>({
    queryKey: queryKeys.incidentDetail(id),
    queryFn: ({ signal }) => getIncidentDetail(id, signal),
    enabled: Number.isInteger(id) && id > 0,
    staleTime: 30_000,
  })
}

/**
 * `/api/v1/actors/{id}` React Query hook — PR #14 Group D.
 *
 * Same subscription + enable discipline as `useReportDetail`.
 *
 * D11 out-of-scope contract: `actorDetailSchema` deliberately has
 * NO `linked_reports` / `reports` / `recent_reports` key — a BE
 * leak would be silently stripped at the parse boundary, so this
 * hook is structurally incapable of surfacing an out-of-scope
 * reports collection on actor detail pages. See
 * `schemas.test.ts::actorDetailSchema_strips_reports_keys` for the
 * FE-side pin.
 */

import { useQuery } from '@tanstack/react-query'

import { getActorDetail } from '../../lib/api/endpoints'
import type { ActorDetail } from '../../lib/api/schemas'
import { queryKeys } from '../../lib/queryKeys'

export function useActorDetail(id: number) {
  return useQuery<ActorDetail>({
    queryKey: queryKeys.actorDetail(id),
    queryFn: ({ signal }) => getActorDetail(id, signal),
    enabled: Number.isInteger(id) && id > 0,
    staleTime: 30_000,
  })
}

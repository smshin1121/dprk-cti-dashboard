/**
 * `/api/v1/actors` list hook — offset pagination only.
 *
 * Filter subscription: NONE. `/actors` has no filter contract on the
 * BE (see `services/api/src/api/routers/actors.py`), so this hook
 * deliberately does not subscribe to the FilterBar store at all.
 * Changing TLP / dateFrom / groupIds does NOT re-render or refetch
 * this query; its cache is scoped purely by pagination.
 *
 * Retry / rate-limit: inherits `retry: false` from the shared
 * QueryClient. On 429, React Query surfaces `ApiError.status=429`
 * through `query.error`; the ListTable renders the specific
 * rate-limit message instead of a generic error.
 */

import { useQuery } from '@tanstack/react-query'

import { listActors } from '../../lib/api/endpoints'
import type { ActorListResponse } from '../../lib/api/schemas'
import type { ActorListPagination } from '../../lib/listFilters'
import { queryKeys } from '../../lib/queryKeys'

export function useActorsList(pagination: ActorListPagination = {}) {
  return useQuery<ActorListResponse>({
    queryKey: queryKeys.actors(pagination),
    queryFn: ({ signal }) => listActors(pagination, signal),
    staleTime: 30_000,
  })
}

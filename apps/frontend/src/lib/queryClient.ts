/**
 * Shared React Query client for the app. One instance per browser
 * session — mounted by `main.tsx` / `App.tsx` (Group B).
 *
 * Global cache-error handling
 * ---------------------------
 * Plan D2.A.2 locks: a 401 from any authenticated endpoint means the
 * session expired. We centralize the reaction here rather than in
 * each individual query so:
 *
 * - Every authenticated query benefits from the same guard
 * - Route-level 401-loop protection lives in one place (`useAuth`)
 * - Logout-initiated cache clears don't race with a 401-triggered
 *   invalidation (`clear()` happens first in `useLogout.onSuccess`,
 *   then the subsequent refetch never fires)
 *
 * On 401, we set the `["me"]` query data to `null`. This flips the
 * route gate (`useAuth`) to "unauthenticated" in one render pass,
 * triggering the redirect to `/login`. We deliberately do NOT
 * `invalidateQueries` on 401 — that would cascade into refetches
 * of every authenticated query which would each 401 in turn,
 * producing a thundering herd against the failing backend.
 *
 * `retry: false` on queries is the default here — React Query's
 * default (3 retries with backoff) masks transient 401s and mixes
 * them up with genuine network errors. Opt-in per query if needed.
 */

import { QueryCache, QueryClient } from '@tanstack/react-query'

import { ApiError } from './api'
import { queryKeys } from './queryKeys'

export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        // staleTime: 0 by default — components that want long-lived
        // caching override per-query (e.g. useMe sets staleTime: Infinity).
        refetchOnWindowFocus: false,
      },
    },
    queryCache: new QueryCache({
      onError: (error) => {
        if (error instanceof ApiError && error.status === 401) {
          // Mark identity as unauth. Route gate re-renders, navigates
          // to /login. Do NOT invalidate — see module docstring.
          client.setQueryData(queryKeys.me(), null)
        }
      },
    }),
  })
  return client
}

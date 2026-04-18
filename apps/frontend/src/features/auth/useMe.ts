/**
 * `/api/v1/auth/me` React Query hook.
 *
 * `staleTime: Infinity` — identity doesn't change within a session;
 * the only events that invalidate `["me"]` are:
 *   1. Logout mutation (explicit invalidation in useLogout)
 *   2. Any query's 401 response (queryCache onError in queryClient.ts
 *      sets `["me"]` data to null, which triggers the route gate)
 *
 * The return type widens the raw query result with a conventional
 * `user: CurrentUser | null` shortcut. `null` specifically denotes
 * "server says unauthenticated" (reached via queryCache 401 handler);
 * `undefined` from React Query's `data` means "not yet loaded"
 * (loading state). Route gates must branch on BOTH — see useAuth.
 */

import { useQuery } from '@tanstack/react-query'

import { getMe } from '../../lib/api/endpoints'
import type { CurrentUser } from '../../lib/api/schemas'
import { queryKeys } from '../../lib/queryKeys'

export function useMe() {
  return useQuery<CurrentUser | null>({
    queryKey: queryKeys.me(),
    queryFn: ({ signal }) => getMe(signal),
    staleTime: Infinity,
    retry: false,
  })
}

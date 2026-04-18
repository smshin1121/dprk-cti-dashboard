/**
 * Logout mutation. Plan D2.A.1 lock: server clears cookie + FE
 * invalidates all cached data.
 *
 * Cache strategy — nuclear clear, not targeted invalidation
 * --------------------------------------------------------
 * On logout success we call `queryClient.clear()`. This removes ALL
 * cached query data (not just `["me"]`). Rationale:
 *
 * - `invalidateQueries()` would trigger refetches of every mounted
 *   query; each would 401 against the now-cookieless session;
 *   queryCache.onError would fire on each one → chaos.
 * - A targeted `setQueryData(["me"], null) + removeQueries(...)`
 *   still leaves stale user-bound data (filters scoped to user's
 *   past context, list cursors derived from user's permissions)
 *   sitting in memory.
 *
 * `clear()` is the correct hammer — post-logout, nothing remains
 * that could render stale user-specific UI. The route gate then
 * redirects to /login where the cache rebuilds from scratch after
 * the next login.
 *
 * Success path
 * ------------
 * Mutation resolves with `null` (204 response). Caller (user-menu
 * logout button handler) observes `mutation.isSuccess` and
 * navigates to `/login`. We do NOT navigate here — that would
 * couple this hook to react-router-dom, which would make
 * unit-testing it require a router wrapper.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'

import { logout } from '../../lib/api/endpoints'

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation<null>({
    mutationFn: () => logout(),
    onSuccess: () => {
      queryClient.clear()
    },
  })
}

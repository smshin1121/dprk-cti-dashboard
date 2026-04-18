/**
 * Auth facade. The canonical read-path hook for components and
 * route gates — do NOT call `useMe()` directly from UI; go through
 * `useAuth()` so the derived `status` stays consistent.
 *
 * Responsibility boundary (plan D10 lock)
 * ---------------------------------------
 * - `user` — full `CurrentUser` DTO from the React Query `["me"]`
 *   cache. Single source of truth for identity.
 * - `status` — derived 3-state enum for UI branching:
 *     'loading'         — initial fetch in flight; render skeletons,
 *                         not redirect. Critical to avoid flashing
 *                         the login page on a real session.
 *     'authenticated'   — query succeeded with a non-null user;
 *                         render protected routes.
 *     'unauthenticated' — query failed with 401 (data cleared by
 *                         queryCache onError) OR data=null. Route
 *                         gate redirects here.
 *
 * There is no 'error' status on purpose — non-401 errors from `/me`
 * are rare and recoverable via inline retry (plan D11). They do not
 * imply unauthenticated; they imply transient backend trouble.
 * Components that care can read `meQuery.error` directly.
 *
 * 401-loop guard (plan D2.A.2)
 * ----------------------------
 * A 401 from `/me` during normal operation = session expired, trigger
 * one redirect to /login. A 401 immediately after login (before
 * any successful `/me` response observed in this session) = config
 * error (CORS misconfigured, cookie domain wrong, Keycloak down).
 * The guard exposes a `hasEverBeenAuthenticated` flag the route
 * gate consults — if the flag is false AND status is unauthenticated,
 * the gate shows a diagnostic error instead of re-looping through
 * the login redirect.
 *
 * The flag lives in useRef, not zustand — it is strictly per-hook-
 * instance scratch space, not an app-level fact worth persisting.
 */

import { useRef } from 'react'

import type { CurrentUser } from '../../lib/api/schemas'
import { useMe } from './useMe'

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

export interface UseAuthResult {
  user: CurrentUser | null
  status: AuthStatus
  /** True iff this hook instance has observed a successful `/me` at least
   *  once. Route gate: if false AND status='unauthenticated', the
   *  situation is a first-boot config failure, not a session expiry. */
  hasEverBeenAuthenticated: boolean
}

export function useAuth(): UseAuthResult {
  const meQuery = useMe()
  const hasEverBeenAuthenticated = useRef(false)

  // Idempotent ref update during render — safe because:
  // 1. It's a ref, not state (no re-render triggered)
  // 2. The condition only flips false→true, never back, so repeated
  //    renders produce identical results
  // 3. Placing this inside a useEffect would defer the update until
  //    AFTER the first render that observes isSuccess, so the return
  //    value of THIS render would still read the pre-update value
  //    (bug caught by test: "flag not set on the render where auth
  //    first succeeds")
  if (meQuery.isSuccess && meQuery.data != null) {
    hasEverBeenAuthenticated.current = true
  }

  const user = meQuery.data ?? null

  let status: AuthStatus
  if (meQuery.isLoading) {
    status = 'loading'
  } else if (user != null) {
    status = 'authenticated'
  } else {
    // `data === null` (queryCache 401 handler set it)
    // OR `meQuery.isError` (non-401 error — still render as
    // unauthenticated from the gate's perspective; the component
    // layer can surface the error via meQuery.error for diagnostic).
    status = 'unauthenticated'
  }

  return {
    user,
    status,
    hasEverBeenAuthenticated: hasEverBeenAuthenticated.current,
  }
}

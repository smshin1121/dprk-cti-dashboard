/**
 * Protected-route gate. Mounts above the Shell layout in the router
 * tree; any route inside its outlet is blocked from rendering until
 * `useAuth()` reports 'authenticated'.
 *
 * Branch semantics (plan D2 + D11):
 *
 * - `status === 'loading'` → <RouteSkeleton/>. No redirect. A real
 *   session's initial `/me` fetch should never flash the login
 *   page; the skeleton buys us that guarantee.
 *
 * - `status === 'unauthenticated'` + `hasEverBeenAuthenticated === true`
 *   → Navigate to /login. Normal session-expiry flow. The path the
 *   user was trying to reach is captured into
 *   `useAuthStore.postLoginRedirect` so the login page can pass it
 *   to the backend's `/auth/login?redirect=...` parameter. Capture
 *   happens in useEffect (side effect) so repeated renders during
 *   the redirect don't overwrite a cleared value.
 *
 * - `status === 'unauthenticated'` + `hasEverBeenAuthenticated === false`
 *   → D2.A.2 lock: first-boot config failure branch. Rather than
 *   redirect to /login (which would loop because the gate fires
 *   again on the redirect target), render an inline diagnostic
 *   card. This indicates backend unreachable, CORS misconfigured,
 *   Keycloak realm missing, or cookie domain mismatch — situations
 *   where redirecting won't help and the user needs an actionable
 *   error.
 *
 * - `status === 'authenticated'` → render the nested <Outlet/>.
 */

import { useEffect } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '../features/auth/useAuth'
import { useAuthStore } from '../stores/auth'
import { RouteSkeleton } from './RouteSkeleton'

export function RouteGate(): JSX.Element {
  const { status, hasEverBeenAuthenticated } = useAuth()
  const location = useLocation()
  const setPostLoginRedirect = useAuthStore((s) => s.setPostLoginRedirect)

  // Capture the intent target when we transition to unauthenticated.
  // useEffect (not render) so we don't write on every render and so
  // `Navigate` below can pair cleanly with the state write.
  useEffect(() => {
    if (status === 'unauthenticated' && hasEverBeenAuthenticated) {
      // Only capture a "real" path — don't remember /login itself as
      // the intent, that would cause post-login bounce to the login
      // page.
      if (location.pathname !== '/login') {
        setPostLoginRedirect(location.pathname + location.search)
      }
    }
  }, [status, hasEverBeenAuthenticated, location.pathname, location.search, setPostLoginRedirect])

  if (status === 'loading') {
    return <RouteSkeleton />
  }

  if (status === 'unauthenticated') {
    if (!hasEverBeenAuthenticated) {
      // First-boot config error. Render diagnostic inline instead
      // of redirecting (would loop; login page would gate again
      // because /me still 401s).
      return (
        <div
          data-testid="route-gate-boot-error"
          role="alert"
          className="m-6 rounded-lg border border-amber-200 bg-amber-50 p-5"
        >
          <p className="text-sm font-semibold uppercase tracking-wider text-amber-800">
            Cannot reach the authentication service
          </p>
          <p className="mt-2 text-sm text-amber-900">
            The API returned an unauthenticated response before this session
            was ever established. Likely causes: backend unreachable, CORS
            misconfiguration, Keycloak realm missing, or session cookie
            domain mismatch. Check the browser devtools Network tab for the
            failing <code>/api/v1/auth/me</code> request.
          </p>
        </div>
      )
    }
    return <Navigate to="/login" replace />
  }

  // authenticated
  return <Outlet />
}

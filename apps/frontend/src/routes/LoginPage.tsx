/**
 * /login — public (unguarded) route.
 *
 * Flow (plan D2):
 * 1. User lands here either by visiting /login directly OR via
 *    RouteGate redirect (session expired or first attempt to access
 *    a protected route).
 * 2. "Sign in" button navigates the browser to the backend's
 *    `/api/v1/auth/login?redirect=<target>` endpoint.
 * 3. BE stashes state + redirects to Keycloak.
 * 4. Keycloak → BE callback → BE sets signed cookie + redirects
 *    to <target>.
 * 5. User lands at <target>, RouteGate sees authenticated session,
 *    renders the protected content.
 *
 * postLoginRedirect source priority (plan D2 + D10):
 * - Prefer the store value (captured by RouteGate on the blocked
 *   navigation attempt). It reflects "where they were trying to go".
 * - Fall back to `/dashboard` if the store is empty (user hit
 *   /login directly with no prior intent).
 *
 * After reading the value, clear it from the store. Stale values
 * must not re-fire on a later visit to /login.
 */

import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'

import { useAuth } from '../features/auth/useAuth'
import { config } from '../config'
import { useAuthStore } from '../stores/auth'

export function LoginPage(): JSX.Element {
  const { status } = useAuth()
  const postLoginRedirect = useAuthStore((s) => s.postLoginRedirect)
  const clearPostLoginRedirect = useAuthStore((s) => s.clearPostLoginRedirect)

  // Snapshot the redirect target on first render so the "Sign in"
  // href stays stable even if the store is cleared later in the
  // same session.
  const [target] = useState(() => postLoginRedirect ?? '/dashboard')

  // Clear on mount so a subsequent visit to /login does not
  // resurrect a stale intent. The snapshot above preserves the
  // value for the sign-in link in this render cycle.
  useEffect(() => {
    if (postLoginRedirect !== null) {
      clearPostLoginRedirect()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // If the user is already authenticated (e.g. opened /login while
  // a valid session exists), skip the page entirely.
  if (status === 'authenticated') {
    return <Navigate to={target} replace />
  }

  const absoluteRedirect = toAbsolute(target)
  const loginHref = `${config.apiUrl}/api/v1/auth/login?redirect=${encodeURIComponent(
    absoluteRedirect,
  )}`

  return (
    <main
      className="flex min-h-screen items-center justify-center bg-app text-ink"
      data-testid="login-page"
    >
      <section className="w-full max-w-md rounded-none border border-border-card bg-surface p-8">
        <p className="text-xs font-cta uppercase tracking-caption text-signal">
          DPRK CTI
        </p>
        <h1 className="mt-3 text-2xl font-display tracking-display">Sign in</h1>
        <p className="mt-2 text-sm text-ink-muted">
          Authentication happens via the Keycloak realm. You will be
          redirected back to your destination after signing in.
        </p>
        <a
          href={loginHref}
          data-testid="login-submit"
          data-login-target={target}
          className="mt-6 inline-flex h-12 w-full items-center justify-center rounded-none bg-primary px-8 text-sm font-cta uppercase tracking-cta text-primary-foreground hover:bg-primary-active active:bg-primary-active"
        >
          Sign in with Keycloak
        </a>
      </section>
    </main>
  )
}

/**
 * The BE `/auth/login?redirect=` expects a fully-qualified URL to
 * validate against its allow-list. Store-captured paths are
 * pathname-only; expand to an absolute URL using the current window
 * origin. No network call — purely local string join.
 */
function toAbsolute(path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) return path
  return `${window.location.origin}${path.startsWith('/') ? path : `/${path}`}`
}

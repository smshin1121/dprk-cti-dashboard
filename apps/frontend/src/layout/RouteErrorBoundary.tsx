/**
 * Route-level error boundary (plan D11 lock).
 *
 * Used as the `errorElement` in the react-router route config so a
 * throwing loader / action / render inside a nested route surfaces
 * here without nuking the whole Shell. Presentation is an inline
 * retry card — "Reload this section" — not a full-page error screen.
 *
 * react-router v6 exposes the thrown value via `useRouteError()`.
 * We recognize three useful cases:
 *
 * 1. `ApiError` with a status — show status + detail.message when
 *    available. Lets ops spot a 500/503 without opening devtools.
 * 2. A plain `Error` — show `error.message`. Fine for client-side
 *    rendering bugs in dev.
 * 3. Anything else (thrown string, non-Error object) — show a
 *    generic "Something went wrong" line.
 *
 * "Retry" is a hard page reload rather than an attempt at smart
 * cache-busting. A route-level error generally means one of the
 * route's queries/loaders failed in a way that left the cache in
 * a weird state; a reload gets the cleanest recovery. Targeted
 * `queryClient.invalidateQueries({ queryKey: ... })` is left to
 * individual components that know which key to invalidate.
 *
 * Plan D11 explicitly forbids a global full-screen error page or
 * blocking spinner — the Shell nav remains interactive during the
 * error so the user can navigate away instead of getting stuck.
 */

import { useRouteError } from 'react-router-dom'

import { ApiError } from '../lib/api'

function describeError(err: unknown): { title: string; detail: string | null } {
  if (err instanceof ApiError) {
    const detailMessage =
      typeof err.detail === 'object' && err.detail !== null && 'message' in err.detail
        ? String((err.detail as { message: unknown }).message)
        : null
    return {
      title: `Request failed (${err.status})`,
      detail: detailMessage,
    }
  }
  if (err instanceof Error) {
    return { title: 'Something went wrong', detail: err.message }
  }
  return { title: 'Something went wrong', detail: null }
}

export function RouteErrorBoundary(): JSX.Element {
  const err = useRouteError()
  const { title, detail } = describeError(err)

  return (
    <div
      data-testid="route-error-boundary"
      role="alert"
      className="m-6 rounded-lg border border-red-200 bg-red-50 p-5"
    >
      <p className="text-sm font-semibold uppercase tracking-wider text-red-800">
        {title}
      </p>
      {detail !== null && (
        <p className="mt-2 text-sm text-red-900" data-testid="route-error-detail">
          {detail}
        </p>
      )}
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="mt-4 rounded border border-red-300 bg-white px-4 py-2 text-sm font-medium text-red-900 hover:bg-red-100"
      >
        Reload this section
      </button>
    </div>
  )
}

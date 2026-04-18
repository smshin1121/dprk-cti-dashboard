/**
 * Router tree. Shape:
 *
 *   /login                        (public — no gate)
 *   <RouteGate>                   (guard — redirects or blocks)
 *     <Shell>                     (layout — nav + outlet)
 *       /                         → redirect to /dashboard
 *       /dashboard                Group E wires KPI strip
 *       /reports                  Group F wires list
 *       /incidents                Group F wires list
 *       /actors                   Group F wires list
 *       *                         404 (inline, no global redirect)
 *
 * D11 policy: each protected route carries the `RouteErrorBoundary`
 * as `errorElement` so a throw inside a loader / render surfaces
 * inline within the Shell, not as a full-screen error. The Shell
 * nav stays interactive during the error.
 */

import {
  Navigate,
  Outlet,
  createBrowserRouter,
} from 'react-router-dom'

import { RouteErrorBoundary } from '../layout/RouteErrorBoundary'
import { RouteGate } from '../layout/RouteGate'
import { Shell } from '../layout/Shell'
import { ActorsPage } from './ActorsPage'
import { DashboardPage } from './DashboardPage'
import { IncidentsPage } from './IncidentsPage'
import { LoginPage } from './LoginPage'
import { ReportsPage } from './ReportsPage'

/**
 * Route-builder that accepts `createBrowserRouter` OR an alternative
 * factory (e.g. `createMemoryRouter` for tests). Tests use
 * `createMemoryRouter` to exercise the same tree without touching
 * the browser history API.
 */
export type RouterFactory = typeof createBrowserRouter

export function buildRouter(factory: RouterFactory = createBrowserRouter) {
  return factory([
    {
      path: '/login',
      element: <LoginPage />,
      errorElement: <RouteErrorBoundary />,
    },
    {
      element: <RouteGate />,
      errorElement: <RouteErrorBoundary />,
      children: [
        {
          element: <Shell />,
          errorElement: <RouteErrorBoundary />,
          children: [
            { index: true, element: <Navigate to="/dashboard" replace /> },
            {
              path: 'dashboard',
              element: <DashboardPage />,
              errorElement: <RouteErrorBoundary />,
            },
            {
              path: 'reports',
              element: <ReportsPage />,
              errorElement: <RouteErrorBoundary />,
            },
            {
              path: 'incidents',
              element: <IncidentsPage />,
              errorElement: <RouteErrorBoundary />,
            },
            {
              path: 'actors',
              element: <ActorsPage />,
              errorElement: <RouteErrorBoundary />,
            },
            {
              path: '*',
              element: <NotFound />,
            },
          ],
        },
      ],
    },
  ])
}

export const router = buildRouter()

function NotFound(): JSX.Element {
  return (
    <section className="m-6 rounded-lg border border-slate-200 bg-white p-5">
      <h1 className="text-lg font-semibold">Not found</h1>
      <p className="mt-2 text-sm text-slate-600">
        This route doesn&apos;t exist. Pick an entry from the nav above.
      </p>
    </section>
  )
}

// Keep Outlet re-exported so tests that bypass the full router can
// still compose a custom outlet-carrying element.
export { Outlet }

/**
 * Router tree. Shape:
 *
 *   /login                        (public — no gate)
 *   <RouteGate>                   (guard — redirects or blocks)
 *     <Shell>                     (layout — nav + outlet)
 *       /                         → redirect to /dashboard
 *       /dashboard                PR #13 Group E/I wires KPI + bottom row
 *       /reports                  list (PR #12)
 *       /reports/:id              report detail (PR #14 Group E)
 *       /incidents                list (PR #12)
 *       /incidents/:id            incident detail (PR #14 Group E)
 *       /actors                   list (PR #12)
 *       /actors/:id               actor detail (PR #14 Group E)
 *       /analytics/correlation    Phase 3 Slice 3 D-1 correlation FE (PR-B T10)
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

import { CorrelationPage } from '../features/analytics/correlation/CorrelationPage'
import { RouteErrorBoundary } from '../layout/RouteErrorBoundary'
import { RouteGate } from '../layout/RouteGate'
import { Shell } from '../layout/Shell'
import { ActorDetailPage } from './ActorDetailPage'
import { ActorsPage } from './ActorsPage'
import { DashboardPage } from './DashboardPage'
import { IncidentDetailPage } from './IncidentDetailPage'
import { IncidentsPage } from './IncidentsPage'
import { LoginPage } from './LoginPage'
import { ReportDetailPage } from './ReportDetailPage'
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
              path: 'reports/:id',
              element: <ReportDetailPage />,
              errorElement: <RouteErrorBoundary />,
            },
            {
              path: 'incidents',
              element: <IncidentsPage />,
              errorElement: <RouteErrorBoundary />,
            },
            {
              path: 'incidents/:id',
              element: <IncidentDetailPage />,
              errorElement: <RouteErrorBoundary />,
            },
            {
              path: 'actors',
              element: <ActorsPage />,
              errorElement: <RouteErrorBoundary />,
            },
            {
              path: 'actors/:id',
              element: <ActorDetailPage />,
              errorElement: <RouteErrorBoundary />,
            },
            {
              path: 'analytics/correlation',
              element: <CorrelationPage />,
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
    <section
      data-page-class="system-page"
      className="m-6 rounded-none border border-border-card bg-surface p-5"
    >
      <h1 className="text-lg font-semibold">Not found</h1>
      <p className="mt-2 text-sm text-ink-muted">
        This route doesn&apos;t exist. Pick an entry from the nav above.
      </p>
    </section>
  )
}

// Keep Outlet re-exported so tests that bypass the full router can
// still compose a custom outlet-carrying element.
export { Outlet }

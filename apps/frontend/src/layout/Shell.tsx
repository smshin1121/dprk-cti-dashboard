/**
 * Outer layout frame for all authenticated routes. Renders a
 * structural top-nav (title + nav links) and an <Outlet/> for the
 * active route. Group C (theme tokens) and Group D (filter bar)
 * fill in the TopNav body; this stub is the mount point for both.
 *
 * Kept intentionally light — no filter state, no KPI strip, no user
 * menu yet. The goal is to prove the mounting contract: a protected
 * route renders inside `<Shell/>`, inside `<RouteGate/>`, and the
 * nav surface is present + interactive the whole time even when the
 * content area is loading (D11 policy).
 */

import { NavLink, Outlet } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/reports', label: 'Reports' },
  { to: '/incidents', label: 'Incidents' },
  { to: '/actors', label: 'Actors' },
] as const

export function Shell(): JSX.Element {
  return (
    <div className="flex min-h-screen flex-col bg-slate-100 text-ink">
      <header
        data-testid="shell-topnav"
        className="flex items-center gap-6 border-b border-grid bg-white px-6 py-4"
      >
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-signal">
          DPRK CTI
        </p>
        <nav className="flex items-center gap-4 text-sm font-medium text-slate-700">
          {NAV_ITEMS.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                isActive
                  ? 'text-signal underline underline-offset-4'
                  : 'hover:text-slate-900'
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main data-testid="shell-main" className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}

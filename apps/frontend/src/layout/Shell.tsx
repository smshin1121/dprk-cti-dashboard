/**
 * Outer layout frame for all authenticated routes. Renders a
 * structural top-nav (title + nav links + theme toggle) and an
 * <Outlet/> for the active route.
 *
 * Token usage (plan D4 lock): every color here goes through a
 * semantic Tailwind class backed by CSS vars (bg-app, bg-surface,
 * text-ink, border-border-card, text-signal). Switching html[data-theme]
 * flips every surface in one repaint without touching component
 * code — test `Shell reflects data-theme attribute via CSS vars`
 * pins this invariant.
 *
 * ThemeToggle lives in the top-nav as a standalone affordance for
 * PR #12. Group G moves it into the user-menu dropdown alongside
 * logout; that refactor keeps `useThemeStore.cycleMode` as the
 * click handler so no behavior change lands with the move.
 */

import { NavLink, Outlet } from 'react-router-dom'

import { ThemeToggle } from '../components/ThemeToggle'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/reports', label: 'Reports' },
  { to: '/incidents', label: 'Incidents' },
  { to: '/actors', label: 'Actors' },
] as const

export function Shell(): JSX.Element {
  return (
    <div className="flex min-h-screen flex-col bg-app text-ink">
      <header
        data-testid="shell-topnav"
        className="flex items-center gap-6 border-b border-border-card bg-surface px-6 py-4"
      >
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-signal">
          DPRK CTI
        </p>
        <nav className="flex flex-1 items-center gap-4 text-sm font-medium text-ink-muted">
          {NAV_ITEMS.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                isActive
                  ? 'text-signal underline underline-offset-4'
                  : 'hover:text-ink'
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <ThemeToggle />
      </header>
      <main data-testid="shell-main" className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}

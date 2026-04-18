/**
 * Outer layout frame for all authenticated routes. Renders a
 * structural top-nav (title + nav links + ⌘K trigger + user menu),
 * a FilterBar, and an <Outlet/> for the active route.
 *
 * Token usage (plan D4 lock): every color here goes through a
 * semantic Tailwind class backed by CSS vars (bg-app, bg-surface,
 * text-ink, border-border-card, text-signal). Switching html[data-theme]
 * flips every surface in one repaint without touching component
 * code — Shell theme test pins this invariant.
 *
 * Group G relocation (plan D5):
 *   - Standalone ThemeToggle removed from the topbar; it now lives
 *     inside UserMenu's dropdown. `useThemeStore.cycleMode` stays
 *     the click handler so behavior is unchanged — only the mount
 *     location moved.
 *   - CommandPaletteButton added to the topbar (⌘K trigger; empty
 *     dialog skeleton per plan §1 non-goal).
 *   - UserMenu added to the topbar; renders only when authenticated
 *     (defensive — Shell normally renders only under RouteGate's
 *     auth branch, but UserMenu has its own null guard for mount
 *     races during logout).
 */

import { NavLink, Outlet } from 'react-router-dom'

import { CommandPaletteButton } from '../components/CommandPaletteButton'
import { UserMenu } from '../components/UserMenu'
import { FilterBar } from './FilterBar'

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
        <CommandPaletteButton />
        <UserMenu />
      </header>
      <FilterBar />
      <main data-testid="shell-main" className="flex-1">
        <Outlet />
      </main>
    </div>
  )
}

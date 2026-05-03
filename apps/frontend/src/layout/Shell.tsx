/**
 * Outer layout frame for all authenticated routes. Renders a
 * structural top-nav (title + nav links + ⌘K trigger + user menu),
 * a FilterBar, and an <Outlet/> for the active route.
 *
 * Token usage (Ferrari L1 lock): every color here goes through a
 * semantic Tailwind class backed by CSS vars (bg-app, bg-surface,
 * text-ink, border-border-card, text-signal). The Ferrari L1 commit
 * collapsed the pre-Ferrari 3-mode theme to a single dark canvas;
 * per-section light editorial bands are opt-in via the
 * `editorial-band-light` class declared in styles/tokens.css.
 *
 * Topbar composition:
 *   - CommandPaletteButton (⌘K trigger).
 *   - UserMenu — renders only when authenticated (defensive — Shell
 *     normally renders only under RouteGate's auth branch, but
 *     UserMenu has its own null guard for mount races during logout).
 */

import { useTranslation } from 'react-i18next'
import { NavLink, Outlet } from 'react-router-dom'

import { CommandPaletteButton } from '../components/CommandPaletteButton'
import { UserMenu } from '../components/UserMenu'
import { useFilterUrlSync } from '../features/url-state/useFilterUrlSync'
import { FilterBar } from './FilterBar'

const NAV_ITEMS = [
  { to: '/dashboard', key: 'shell.nav.dashboard' },
  { to: '/reports', key: 'shell.nav.reports' },
  { to: '/incidents', key: 'shell.nav.incidents' },
  { to: '/actors', key: 'shell.nav.actors' },
] as const

export function Shell(): JSX.Element {
  // Plan D4 URL-state sync (PR #13 Group E). Runs on every
  // authenticated route so filter + dashboard view/tab stay in sync
  // with the URL. Hook is void-returning; no render-level effect.
  useFilterUrlSync()
  const { t } = useTranslation()

  return (
    <div className="flex min-h-screen flex-col bg-app text-ink">
      <header
        data-testid="shell-topnav"
        className="flex items-center gap-6 border-b border-border-card bg-surface px-6 py-4"
      >
        <p className="text-sm font-bold uppercase tracking-[0.2em] text-signal">
          {t('shell.brand')}
        </p>
        <nav className="flex flex-1 items-center gap-4 text-sm font-medium text-ink-muted">
          {NAV_ITEMS.map(({ to, key }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                isActive
                  ? 'text-signal underline underline-offset-4'
                  : 'hover:text-ink'
              }
            >
              {t(key)}
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

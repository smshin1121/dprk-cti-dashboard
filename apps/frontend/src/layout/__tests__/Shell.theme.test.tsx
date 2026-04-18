import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { useThemeStore } from '../../stores/theme'
import { Shell } from '../Shell'

// Shell integration for the theme surface — Group G relocated the
// toggle from standalone topbar → inside UserMenu's dropdown. The
// invariant being tested shifts with it: the toggle no longer lives
// as a direct topbar descendant, but it must still be reachable
// from the topbar's user menu and still flip html[data-theme] when
// clicked. Plus the topbar itself remains on semantic tokens.

const ME_BODY = {
  sub: 'abc-123',
  email: 'analyst@dprk.test',
  name: 'Jane Analyst',
  roles: ['analyst'],
}

function renderShell(initialPath = '/') {
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      {
        element: <Shell />,
        children: [
          { path: '/', element: <div data-testid="outlet-content" /> },
        ],
      },
    ],
    { initialEntries: [initialPath] },
  )
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<RouterProvider router={router} />, { wrapper: Wrapper })
}

function resetTheme(): void {
  document.documentElement.removeAttribute('data-theme')
  window.localStorage.clear()
  useThemeStore.setState({ mode: 'system' })
}

beforeEach(() => {
  resetTheme()
  vi.spyOn(global, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(ME_BODY), { status: 200 }),
  )
})

afterEach(() => vi.restoreAllMocks())

describe('Shell topbar — theme surface (plan D4 + D5 + Group G relocation)', () => {
  it('topbar no longer contains ThemeToggle directly (moved to UserMenu per Group G)', async () => {
    renderShell()
    await waitFor(() =>
      expect(screen.getByTestId('user-menu-trigger')).toBeInTheDocument(),
    )
    const topnav = screen.getByTestId('shell-topnav')
    // Before Group G the ThemeToggle lived here. After Group G it's
    // inside the user-menu portal — which renders into document.body,
    // not into the topbar DOM subtree.
    expect(topnav.querySelector('[data-testid="theme-toggle"]')).toBeNull()
  })

  it('user-menu dropdown exposes the ThemeToggle + clicking flips data-theme live', async () => {
    const user = userEvent.setup()
    useThemeStore.getState().setMode('light')
    renderShell()
    await waitFor(() =>
      expect(screen.getByTestId('user-menu-trigger')).toBeInTheDocument(),
    )
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')

    await user.click(screen.getByTestId('user-menu-trigger'))
    const toggle = await screen.findByTestId('theme-toggle')
    await user.click(toggle)
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })

  it('topbar also hosts the ⌘K trigger (Group G scope — trigger only, no search surface)', async () => {
    renderShell()
    const topnav = screen.getByTestId('shell-topnav')
    expect(topnav.querySelector('[data-testid="cmdk-trigger"]')).not.toBeNull()
    // The dialog content lives in a portal; it is NOT inside the
    // topbar. The button that opens it IS — that's the plan D5
    // surface we promise to ship in PR #12.
  })

  it('topbar uses semantic theme tokens (class-name surface pin)', () => {
    renderShell()
    const topnav = screen.getByTestId('shell-topnav')
    // A failing assertion here means someone regressed the Shell
    // back to hardcoded slate-100/white classes that don't flip on
    // theme change — which defeats D4.
    const className = topnav.className
    expect(className).toMatch(/\bbg-surface\b/)
    expect(className).toMatch(/\bborder-border-card\b/)
    expect(className).not.toMatch(/\bbg-white\b/)
  })
})

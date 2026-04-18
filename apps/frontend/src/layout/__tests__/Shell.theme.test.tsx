import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import { useThemeStore } from '../../stores/theme'
import { Shell } from '../Shell'

// Shell integration: proves the ThemeToggle is mounted on the topbar
// AND that clicking it flips html[data-theme]. Existing Shell tests
// in RouteGate/router suites cover nav + outlet; this file pins the
// D4/D5 surface — "palette toggle과 topbar 반영" per review focus.

function renderShell(initialPath = '/') {
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
  return render(<RouterProvider router={router} />)
}

function resetTheme(): void {
  document.documentElement.removeAttribute('data-theme')
  window.localStorage.clear()
  useThemeStore.setState({ mode: 'system' })
}

describe('Shell topbar — ThemeToggle integration (plan D4 + D5)', () => {
  beforeEach(resetTheme)

  it('mounts ThemeToggle inside the topbar', () => {
    renderShell()
    const topnav = screen.getByTestId('shell-topnav')
    const toggle = screen.getByTestId('theme-toggle')
    // The toggle must be a descendant of the topbar — not floating
    // elsewhere in the Shell. D5 locks the topbar as its location
    // until Group G relocates to the user menu.
    expect(topnav.contains(toggle)).toBe(true)
  })

  it('clicking toggle flips html[data-theme] live', async () => {
    const user = userEvent.setup()
    useThemeStore.getState().setMode('light')
    renderShell()
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')

    await user.click(screen.getByTestId('theme-toggle'))
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')

    await user.click(screen.getByTestId('theme-toggle'))
    expect(document.documentElement.getAttribute('data-theme')).toBe('system')
  })

  it('topbar uses semantic theme tokens (class-name surface pin)', () => {
    renderShell()
    const topnav = screen.getByTestId('shell-topnav')
    // A failing assertion here means someone regressed the Shell
    // back to hardcoded slate-100/white classes that don't flip on
    // theme change — which defeats D4. We check Tailwind class
    // strings because CSS-var computed values go through jsdom and
    // happy-dom's inconsistent CSS engine would give flaky results.
    const className = topnav.className
    expect(className).toMatch(/\bbg-surface\b/)
    expect(className).toMatch(/\bborder-border-card\b/)
    expect(className).not.toMatch(/\bbg-white\b/)
  })
})

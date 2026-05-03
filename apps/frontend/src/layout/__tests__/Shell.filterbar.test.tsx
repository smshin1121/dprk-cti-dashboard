import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { useFilterStore } from '../../stores/filters'
import { Shell } from '../Shell'

// Group G introduced UserMenu into the Shell, which calls useAuth →
// useMe → useQuery. Shell integration tests now need a QueryClient
// wrapper and a mocked /me response so the topbar mounts fully.

function renderShell() {
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
    { initialEntries: ['/'] },
  )
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<RouterProvider router={router} />, { wrapper: Wrapper })
}

function resetStore(): void {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
}

describe('Shell — FilterBar integration (plan D5)', () => {
  beforeEach(() => {
    resetStore()
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          sub: 'x',
          email: 'analyst@dprk.test',
          name: null,
          roles: ['analyst'],
        }),
        { status: 200 },
      ),
    )
  })
  afterEach(() => vi.restoreAllMocks())

  it('mounts FilterBar inside the Shell layout', () => {
    renderShell()
    expect(screen.getByTestId('filter-bar')).toBeInTheDocument()
  })

  it('FilterBar sits above the main outlet, below the topbar', () => {
    renderShell()
    const topnav = screen.getByTestId('shell-topnav')
    const filterBar = screen.getByTestId('filter-bar')
    const main = screen.getByTestId('shell-main')

    // Document order: topbar → filter-bar → main. compareDocumentPosition
    // returns FOLLOWING (0x04) when the other node is after `this`.
    const FOLLOWING = Node.DOCUMENT_POSITION_FOLLOWING
    expect(topnav.compareDocumentPosition(filterBar) & FOLLOWING).toBeTruthy()
    expect(filterBar.compareDocumentPosition(main) & FOLLOWING).toBeTruthy()
  })

  // Topbar integration coverage migrated from the deleted Shell.theme
  // test file (Ferrari L1 collapsed the 3-mode theme; the non-theme
  // assertions about cmdk-trigger mount + semantic-token classes are
  // not theme-specific so they live here.)
  it('topbar mounts the command-palette trigger inside shell-topnav', async () => {
    renderShell()
    // Wait for the topnav to be in the document, then scope the
    // trigger lookup to shell-topnav (not the document) so a
    // future move of cmdk-trigger out of the topbar fails this
    // test loud — matches the deleted Shell.theme.test.tsx scope.
    const topnav = await screen.findByTestId('shell-topnav')
    const trigger = topnav.querySelector('[data-testid="cmdk-trigger"]')
    expect(trigger).not.toBeNull()
  })

  it('topbar uses semantic surface tokens (Ferrari L1 — no raw hex)', () => {
    renderShell()
    const topnav = screen.getByTestId('shell-topnav')
    // The topbar's surface class is one of the semantic tokens
    // (bg-app or bg-surface) — NOT a raw color hex. The Ferrari
    // realignment may swap bg-surface → bg-app at L2 to match
    // DESIGN.md §Top Navigation `top-nav-on-dark` (canvas bg);
    // both options are semantic. The hairline divider is pinned to
    // border-border-card so a tokens.css edit cannot silently
    // regress the topbar surface boundary.
    expect(topnav.className).toMatch(/\bbg-(app|surface)\b/)
    expect(topnav.className).toMatch(/\bborder-border-card\b/)
    // Negative guard — no raw white background. Ferrari L1 lock:
    // the dark canvas is the global surface; light read-through is
    // opt-in via .editorial-band-light, never via raw bg-white on
    // structural chrome.
    expect(topnav.className).not.toMatch(/\bbg-white\b/)
  })
})

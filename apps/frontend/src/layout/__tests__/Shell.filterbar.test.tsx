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
})

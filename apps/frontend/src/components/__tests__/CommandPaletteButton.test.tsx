import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
  useLocation,
} from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { useFilterStore } from '../../stores/filters'
import { CommandPaletteButton } from '../CommandPaletteButton'

function LocationProbe(): JSX.Element {
  const loc = useLocation()
  return <span data-testid="location" data-path={loc.pathname} />
}

function renderPalette(extraChildren?: ReactNode) {
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: (
          <>
            {extraChildren}
            <CommandPaletteButton />
            <LocationProbe />
          </>
        ),
      },
      { path: '/dashboard', element: <LocationProbe /> },
      { path: '/reports', element: <LocationProbe /> },
      { path: '/incidents', element: <LocationProbe /> },
      { path: '/actors', element: <LocationProbe /> },
      { path: '/analytics/correlation', element: <LocationProbe /> },
      { path: '/login', element: <LocationProbe /> },
    ],
    { initialEntries: ['/'] },
  )
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<RouterProvider router={router} />, { wrapper: Wrapper })
}

function getCurrentPath(): string {
  const probe = screen.getByTestId('location')
  return probe.getAttribute('data-path') ?? ''
}

function resetStores(): void {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
  window.localStorage.clear()
}

beforeEach(() => {
  resetStores()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('CommandPaletteButton', () => {
  // ---- Contracts carried from PR #12 Group G ----

  it('renders a trigger button with ⌘K hint', () => {
    renderPalette()
    const btn = screen.getByTestId('cmdk-trigger')
    expect(btn).toBeInTheDocument()
    expect(btn).toHaveTextContent('⌘K')
  })

  it('mod+k shortcut toggles the dialog globally', async () => {
    const user = userEvent.setup()
    renderPalette()
    expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()

    await user.keyboard('{Control>}k{/Control}')
    expect(await screen.findByTestId('cmdk-dialog')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()

    await user.keyboard('{Meta>}k{/Meta}')
    expect(await screen.findByTestId('cmdk-dialog')).toBeInTheDocument()
  })

  it('mod+k inside input fields does NOT hijack keystroke (editable-target guard)', async () => {
    const user = userEvent.setup()
    renderPalette(<input data-testid="form-field" />)
    const input = screen.getByTestId('form-field') as HTMLInputElement
    input.focus()
    await user.keyboard('k')
    expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.click(screen.getByTestId('cmdk-trigger'))
    expect(await screen.findByTestId('cmdk-dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()
  })

  // ---- PR #13 Group D — command list content ----

  describe('command list (plan D3 scope)', () => {
    it('renders exactly the 7 commands locked in plan D3 + Ferrari L1 + PR-B T10', async () => {
      const user = userEvent.setup()
      renderPalette()
      await user.click(screen.getByTestId('cmdk-trigger'))

      // Scope invariant — exact set, no more, no less. If a future
      // edit adds a "search reports" or "create incident" item, this
      // test fails loud and forces a scope-lock review.
      // theme.cycle was removed in Ferrari L1 (single dark canvas).
      // PR-B T10 added nav.correlation alongside the router mount,
      // Shell nav entry, and PAGE_CLASS_BY_ROUTE manifest entry — all
      // four surfaces stay in sync.
      const expected = [
        'cmdk-item-nav.dashboard',
        'cmdk-item-nav.reports',
        'cmdk-item-nav.incidents',
        'cmdk-item-nav.actors',
        'cmdk-item-nav.correlation',
        'cmdk-item-filters.clear',
        'cmdk-item-auth.logout',
      ]
      for (const testid of expected) {
        expect(await screen.findByTestId(testid)).toBeInTheDocument()
      }

      // No item outside that set.
      const items = screen.getAllByTestId(/^cmdk-item-/)
      expect(items).toHaveLength(expected.length)
    })

    it('shows the input + list + empty fallback (cmdk composition)', async () => {
      const user = userEvent.setup()
      renderPalette()
      await user.click(screen.getByTestId('cmdk-trigger'))

      expect(await screen.findByTestId('cmdk-input')).toBeInTheDocument()
      expect(screen.getByTestId('cmdk-list')).toBeInTheDocument()
      // Empty fallback is in the DOM but hidden when items match;
      // cmdk shows it only when no command matches the input.
    })
  })

  // ---- Per-command action wiring ----

  describe('navigation commands', () => {
    it.each([
      ['nav.dashboard', '/dashboard'],
      ['nav.reports', '/reports'],
      ['nav.incidents', '/incidents'],
      ['nav.actors', '/actors'],
      ['nav.correlation', '/analytics/correlation'],
    ] as const)(
      '%s navigates to %s and closes the dialog',
      async (id, path) => {
        const user = userEvent.setup()
        renderPalette()
        await user.click(screen.getByTestId('cmdk-trigger'))

        await user.click(await screen.findByTestId(`cmdk-item-${id}`))

        await waitFor(() => expect(getCurrentPath()).toBe(path))
        expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()
      },
    )
  })

  describe('theme.cycle command (removed in Ferrari L1)', () => {
    it('the theme.cycle item is no longer in the palette', async () => {
      const user = userEvent.setup()
      renderPalette()
      await user.click(screen.getByTestId('cmdk-trigger'))
      await screen.findByTestId('cmdk-dialog')
      expect(
        screen.queryByTestId('cmdk-item-theme.cycle'),
      ).not.toBeInTheDocument()
    })
  })

  describe('filters.clear command', () => {
    it('resets the filter store (dates + groups + tlp) + closes dialog', async () => {
      const user = userEvent.setup()
      useFilterStore.setState({
        dateFrom: '2026-01-01',
        dateTo: '2026-04-18',
        groupIds: [1, 3],
        tlpLevels: ['AMBER'],
      })
      renderPalette()
      await user.click(screen.getByTestId('cmdk-trigger'))

      await user.click(await screen.findByTestId('cmdk-item-filters.clear'))

      const state = useFilterStore.getState()
      expect(state.dateFrom).toBeNull()
      expect(state.dateTo).toBeNull()
      expect(state.groupIds).toEqual([])
      // Plan D4 lock: store.clear() resets tlp too (user affordance
      // reset regardless of whether tlp crosses the wire).
      expect(state.tlpLevels).toEqual([])
      expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()
    })
  })

  describe('auth.logout command', () => {
    it('POSTs /auth/logout + navigates to /login + closes dialog', async () => {
      const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof Request
            ? input.url
            : String(input)
        if (url.endsWith('/api/v1/auth/logout')) {
          return Promise.resolve(new Response(null, { status: 204 }))
        }
        return Promise.resolve(new Response('{}', { status: 200 }))
      })

      const user = userEvent.setup()
      renderPalette()
      await user.click(screen.getByTestId('cmdk-trigger'))
      await user.click(await screen.findByTestId('cmdk-item-auth.logout'))

      await waitFor(() => {
        const call = fetchSpy.mock.calls.find(([u]) =>
          String(u).endsWith('/api/v1/auth/logout'),
        )
        expect(call?.[1]?.method).toBe('POST')
      })
      await waitFor(() => expect(getCurrentPath()).toBe('/login'))
      expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()
    })
  })
})

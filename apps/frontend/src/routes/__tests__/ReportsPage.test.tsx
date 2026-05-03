import { QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { useFilterStore } from '../../stores/filters'
import { useReportsViewModeStore } from '../../stores/reportsViewMode'
import { ReportsPage } from '../ReportsPage'

function renderWithRouter() {
  const client = createQueryClient()
  const router = createMemoryRouter(
    [{ path: '/reports', element: <ReportsPage /> }],
    { initialEntries: ['/reports'] },
  )
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<RouterProvider router={router} />, { wrapper: Wrapper })
}

const lazarusReport = {
  id: 42,
  title: 'Lazarus report',
  url: 'https://example.test/1',
  url_canonical: 'https://example.test/1',
  published: '2026-03-15',
  source_id: 7,
  source_name: 'Mandiant',
  lang: 'en',
  tlp: 'WHITE',
}

beforeEach(() => {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
  window.localStorage.clear()
  useReportsViewModeStore.setState({ mode: 'list' })
})

afterEach(() => vi.restoreAllMocks())

describe('ReportsPage', () => {
  it('renders a row and links the title externally', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ items: [lazarusReport], next_cursor: null }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() => {
      const link = screen.getByText('Lazarus report') as HTMLAnchorElement
      expect(link.tagName).toBe('A')
      expect(link.getAttribute('href')).toBe('https://example.test/1')
      expect(link.getAttribute('rel')).toContain('noreferrer')
    })
  })

  it('Next button pushes next_cursor onto stack', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [lazarusReport],
          next_cursor: 'cur-page-2',
        }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() => expect(screen.getByText('Lazarus report')).toBeInTheDocument())
    expect(spy).toHaveBeenCalledTimes(1)

    await userEvent.setup().click(screen.getByTestId('reports-next'))
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    const second = new URL(String(spy.mock.calls[1][0]))
    expect(second.searchParams.get('cursor')).toBe('cur-page-2')
  })

  it('Previous is disabled on first page', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ items: [lazarusReport], next_cursor: 'x' }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() => expect(screen.getByText('Lazarus report')).toBeInTheDocument())
    expect(screen.getByTestId('reports-prev')).toBeDisabled()
  })

  it('changing date range in the filter store refetches with new date_from', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ items: [lazarusReport], next_cursor: null }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))

    useFilterStore.getState().setDateRange('2026-01-01', null)
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    const second = new URL(String(spy.mock.calls[1][0]))
    expect(second.searchParams.get('date_from')).toBe('2026-01-01')
  })

  it('changing date range resets stale pagination cursors', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [lazarusReport],
          next_cursor: 'cur-page-2',
        }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))

    await userEvent.setup().click(screen.getByTestId('reports-next'))
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    const second = new URL(String(spy.mock.calls[1][0]))
    expect(second.searchParams.get('cursor')).toBe('cur-page-2')

    act(() => {
      useFilterStore.getState().setDateRange('2024-01-01', '2024-12-31')
    })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(3))
    const third = new URL(String(spy.mock.calls[2][0]))
    expect(third.searchParams.get('date_from')).toBe('2024-01-01')
    expect(third.searchParams.get('date_to')).toBe('2024-12-31')
    expect(third.searchParams.get('cursor')).toBeNull()
  })

  it('mounts the view-mode toggle in the header', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ items: [lazarusReport], next_cursor: null }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() =>
      expect(screen.getByText('Lazarus report')).toBeInTheDocument(),
    )
    expect(
      screen.getByTestId('reports-view-mode-toggle'),
    ).toBeInTheDocument()
  })

  it('toggling view mode swaps ListTable for ReportTimeline (single fetch)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ items: [lazarusReport], next_cursor: null }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() =>
      expect(screen.getByText('Lazarus report')).toBeInTheDocument(),
    )
    // Initial: list mode → table caption present, timeline absent
    expect(screen.getByText('Reports list')).toBeInTheDocument()
    expect(screen.queryByTestId('reports-timeline')).not.toBeInTheDocument()

    await userEvent
      .setup()
      .click(screen.getByTestId('reports-view-mode-toggle'))

    // After toggle: timeline present, table caption gone
    await waitFor(() =>
      expect(screen.getByTestId('reports-timeline')).toBeInTheDocument(),
    )
    expect(screen.queryByText('Reports list')).not.toBeInTheDocument()

    // Same React-Query cache — no extra fetch
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('hydrates with the persisted view mode on mount', async () => {
    useReportsViewModeStore.setState({ mode: 'timeline' })
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ items: [lazarusReport], next_cursor: null }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() =>
      expect(screen.getByTestId('reports-timeline')).toBeInTheDocument(),
    )
    expect(screen.queryByText('Reports list')).not.toBeInTheDocument()
  })
})

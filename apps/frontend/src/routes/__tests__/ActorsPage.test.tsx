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
import { useFilterStore } from '../../stores/filters'
import { ActorsPage } from '../ActorsPage'

function renderWithRouter() {
  const client = createQueryClient()
  const router = createMemoryRouter(
    [{ path: '/actors', element: <ActorsPage /> }],
    { initialEntries: ['/actors'] },
  )
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<RouterProvider router={router} />, { wrapper: Wrapper })
}

const lazarusRow = {
  id: 3,
  name: 'Lazarus Group',
  mitre_intrusion_set_id: 'G0032',
  aka: ['APT38'],
  description: null,
  codenames: ['Andariel'],
}

beforeEach(() => {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
})

afterEach(() => vi.restoreAllMocks())

describe('ActorsPage', () => {
  it('renders the first page when the endpoint returns a non-empty list', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [lazarusRow],
          limit: 50,
          offset: 0,
          total: 1,
        }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() =>
      expect(screen.getByText('Lazarus Group')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('actors-pagination')).toHaveTextContent(
      'Showing 1–1 of 1',
    )
    // Pagination buttons: prev disabled (first page), next disabled
    // (only one page of 1 row, PAGE_SIZE 50).
    expect(screen.getByTestId('actors-prev')).toBeDisabled()
    expect(screen.getByTestId('actors-next')).toBeDisabled()
  })

  it('renders the empty-state card when items is empty', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ items: [], limit: 50, offset: 0, total: 0 }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() =>
      expect(screen.getByTestId('list-table-empty')).toBeInTheDocument(),
    )
  })

  it('renders the rate-limit message on 429', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ error: 'rate_limit_exceeded' }),
        { status: 429 },
      ),
    )
    renderWithRouter()
    await waitFor(() =>
      expect(screen.getByTestId('list-table-error-rate-limit')).toBeInTheDocument(),
    )
  })

  it('Next button issues a second fetch with offset=PAGE_SIZE', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [lazarusRow],
          limit: 50,
          offset: 0,
          total: 120, // forces hasNext=true
        }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() =>
      expect(screen.getByText('Lazarus Group')).toBeInTheDocument(),
    )
    expect(spy).toHaveBeenCalledTimes(1)

    await userEvent.setup().click(screen.getByTestId('actors-next'))
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    const second = new URL(String(spy.mock.calls[1][0]))
    expect(second.searchParams.get('offset')).toBe('50')
  })
})

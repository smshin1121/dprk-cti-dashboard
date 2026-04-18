import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { useFilterStore } from '../../stores/filters'
import { IncidentsPage } from '../IncidentsPage'

function renderWithRouter() {
  const client = createQueryClient()
  const router = createMemoryRouter(
    [{ path: '/incidents', element: <IncidentsPage /> }],
    { initialEntries: ['/incidents'] },
  )
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<RouterProvider router={router} />, { wrapper: Wrapper })
}

const roninIncident = {
  id: 18,
  reported: '2024-05-02',
  title: 'Axie Infinity Ronin bridge exploit',
  description: '620M USD bridge compromise',
  est_loss_usd: 620000000,
  attribution_confidence: 'HIGH',
  motivations: ['financial'],
  sectors: ['crypto'],
  countries: ['VN', 'SG'],
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

describe('IncidentsPage', () => {
  it('renders a row with motivations + countries + formatted loss', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ items: [roninIncident], next_cursor: null }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() =>
      expect(screen.getByText('Axie Infinity Ronin bridge exploit')).toBeInTheDocument(),
    )
    expect(screen.getByText('financial')).toBeInTheDocument()
    expect(screen.getByText('VN, SG')).toBeInTheDocument()
    // USD currency formatting, at least the $ prefix + the thousands
    // separators.
    expect(screen.getByText(/\$620,000,000/)).toBeInTheDocument()
  })

  it('renders empty state when next_cursor null and items empty', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ items: [], next_cursor: null }),
        { status: 200 },
      ),
    )
    renderWithRouter()
    await waitFor(() =>
      expect(screen.getByTestId('list-table-empty')).toBeInTheDocument(),
    )
  })
})

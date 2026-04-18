import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { MotivationDonut } from '../MotivationDonut'

const SUMMARY_BODY = {
  total_reports: 10,
  total_incidents: 5,
  total_actors: 3,
  reports_by_year: [{ year: 2026, count: 10 }],
  incidents_by_motivation: [
    { motivation: 'financial', count: 3 },
    { motivation: 'espionage', count: 2 },
  ],
  top_groups: [],
}

const EMPTY_MOTIVATION_BODY = {
  ...SUMMARY_BODY,
  incidents_by_motivation: [],
}

function makeWrapper() {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return { client, Wrapper }
}

beforeEach(() => {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('MotivationDonut', () => {
  it('loading state', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<MotivationDonut />, { wrapper: Wrapper })
    expect(screen.getByTestId('motivation-donut-loading')).toBeInTheDocument()
  })

  it('error state with retry button', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<MotivationDonut />, { wrapper: Wrapper })
    expect(await screen.findByTestId('motivation-donut-error')).toBeInTheDocument()
    expect(screen.getByTestId('motivation-donut-retry')).toBeInTheDocument()
  })

  it('empty state when incidents_by_motivation is empty', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_MOTIVATION_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<MotivationDonut />, { wrapper: Wrapper })
    expect(await screen.findByTestId('motivation-donut-empty')).toBeInTheDocument()
    // Donut chart itself not rendered when empty (avoid degenerate
    // zero-slice pie).
    expect(screen.queryByTestId('motivation-donut')).not.toBeInTheDocument()
  })

  it('populated state renders one slice per motivation with data attributes', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<MotivationDonut />, { wrapper: Wrapper })

    expect(await screen.findByTestId('motivation-donut')).toBeInTheDocument()
    expect(
      screen.getByTestId('motivation-donut-slice-financial'),
    ).toHaveAttribute('data-count', '3')
    expect(
      screen.getByTestId('motivation-donut-slice-espionage'),
    ).toHaveAttribute('data-count', '2')
  })

  it('uses /api/v1/dashboard/summary — same endpoint as KPIStrip', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(SUMMARY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<MotivationDonut />, { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/dashboard/summary')
  })
})

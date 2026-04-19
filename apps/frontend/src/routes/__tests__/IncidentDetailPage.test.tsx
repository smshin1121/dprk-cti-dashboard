import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { IncidentDetailPage } from '../IncidentDetailPage'

function ReportDetailStub(): JSX.Element {
  return <div data-testid="report-detail-stub">report detail stub</div>
}

function renderAt(initialPath: string) {
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      { path: '/incidents/:id', element: <IncidentDetailPage /> },
      { path: '/reports/:id', element: <ReportDetailStub /> },
    ],
    { initialEntries: [initialPath] },
  )
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<RouterProvider router={router} />, { wrapper: Wrapper })
}

// BE IncidentDetail example[0] — with one linked_report.
const HAPPY_BODY = {
  id: 18,
  reported: '2024-05-02',
  title: 'Axie Infinity Ronin bridge exploit',
  description: '620M USD bridge compromise attributed to Lazarus',
  est_loss_usd: 620_000_000,
  attribution_confidence: 'HIGH',
  motivations: ['financial'],
  sectors: ['crypto'],
  countries: ['VN', 'SG'],
  linked_reports: [
    {
      id: 42,
      title: 'Lazarus targets SK crypto exchanges',
      url: 'https://mandiant.com/blog/lazarus-2026q1',
      published: '2026-03-15',
      source_name: 'Mandiant',
    },
  ],
}

afterEach(() => vi.restoreAllMocks())

describe('IncidentDetailPage', () => {
  it('renders loading skeleton while fetch is pending', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    renderAt('/incidents/18')
    expect(screen.getByTestId('incident-detail-loading')).toBeInTheDocument()
  })

  it('renders populated detail fields', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderAt('/incidents/18')

    await waitFor(() =>
      expect(screen.getByTestId('incident-detail-page')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('incident-detail-page')).toHaveAttribute(
      'data-incident-id',
      '18',
    )
    expect(
      screen.getByText('Axie Infinity Ronin bridge exploit'),
    ).toBeInTheDocument()
    expect(screen.getByText('financial')).toBeInTheDocument()
    expect(screen.getByText('VN, SG')).toBeInTheDocument()
    expect(screen.getByText(/\$620,000,000/)).toBeInTheDocument()
    expect(screen.getByText('HIGH')).toBeInTheDocument()

    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/incidents/18')
  })

  // D11 — linked_reports summaries link to /reports/:id. No external
  // URL on this surface (reachable only via the report detail page).
  it('renders linked_reports with Links to /reports/:id (D11)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderAt('/incidents/18')

    await waitFor(() =>
      expect(
        screen.getByTestId('incident-detail-linked-reports'),
      ).toBeInTheDocument(),
    )
    const row = screen.getByTestId('incident-detail-linked-report-42')
    expect(row).toHaveAttribute('data-report-id', '42')
    const link = row.querySelector('a')
    expect(link).not.toBeNull()
    expect(link!.getAttribute('href')).toBe('/reports/42')
    expect(link!.getAttribute('target')).not.toBe('_blank')
    expect(link!.textContent).toContain('Lazarus targets SK crypto exchanges')
  })

  it('renders sparse incident (all-null + empty collections)', async () => {
    const sparseBody = {
      id: 99,
      reported: null,
      title: 'Incident without source reports yet',
      description: null,
      est_loss_usd: null,
      attribution_confidence: null,
      motivations: [],
      sectors: [],
      countries: [],
      linked_reports: [],
    }
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(sparseBody), { status: 200 }),
    )
    renderAt('/incidents/99')
    await waitFor(() =>
      expect(screen.getByTestId('incident-detail-page')).toBeInTheDocument(),
    )
    expect(
      screen.queryByTestId('incident-detail-linked-reports'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('incident-detail-description'),
    ).not.toBeInTheDocument()
  })

  it('404 response renders NotFound panel', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('not found', { status: 404 }),
    )
    renderAt('/incidents/9999')
    await waitFor(() =>
      expect(
        screen.getByTestId('incident-detail-notfound'),
      ).toBeInTheDocument(),
    )
  })

  it('malformed path param renders NotFound without fetching', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderAt('/incidents/not-a-number')
    expect(
      screen.getByTestId('incident-detail-notfound'),
    ).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 20))
    expect(spy).not.toHaveBeenCalled()
  })
})

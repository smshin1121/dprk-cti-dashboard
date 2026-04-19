import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { ReportDetailPage } from '../ReportDetailPage'

// PR #14 Group F mounted SimilarReportsPanel at the bottom of the
// report detail page. These tests dispatch fetch mocks by pathname
// so the panel gets a D10 empty contract by default; tests that
// specifically exercise the populated panel pass their own body.
function dispatchFetch(detailResponse: Response, similarResponse?: Response) {
  return vi.spyOn(global, 'fetch').mockImplementation(async (input) => {
    const url = new URL(String(input), 'http://x.test')
    if (url.pathname.endsWith('/similar')) {
      return (
        similarResponse ??
        new Response(JSON.stringify({ items: [] }), { status: 200 })
      )
    }
    return detailResponse.clone()
  })
}

// Mock /incidents/:id with a sentinel so Linked-incident click
// navigation can be verified without pulling the real page + its
// hook's fetch wiring into this test.
function IncidentDetailStub(): JSX.Element {
  return <div data-testid="incident-detail-stub">incident detail stub</div>
}

function renderAt(initialPath: string) {
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      { path: '/reports/:id', element: <ReportDetailPage /> },
      { path: '/incidents/:id', element: <IncidentDetailStub /> },
    ],
    { initialEntries: [initialPath] },
  )
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<RouterProvider router={router} />, { wrapper: Wrapper })
}

// BE ReportDetail example[0] — with one linked_incident.
const HAPPY_BODY = {
  id: 42,
  title: 'Lazarus targets South Korean crypto exchanges',
  url: 'https://mandiant.com/blog/lazarus-2026q1',
  url_canonical: 'https://mandiant.com/blog/lazarus-2026q1',
  published: '2026-03-15',
  source_id: 7,
  source_name: 'Mandiant',
  lang: 'en',
  tlp: 'WHITE',
  summary: 'Operation targeting crypto exchanges in Q1 2026.',
  reliability: 'A',
  credibility: '2',
  tags: ['ransomware', 'finance'],
  codenames: ['Andariel'],
  techniques: ['T1566', 'T1190'],
  linked_incidents: [
    { id: 18, title: 'Axie Infinity Ronin bridge exploit', reported: '2024-05-02' },
  ],
}

afterEach(() => vi.restoreAllMocks())

describe('ReportDetailPage', () => {
  it('renders loading skeleton while fetch is pending', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    renderAt('/reports/42')
    expect(screen.getByTestId('report-detail-loading')).toBeInTheDocument()
  })

  it('renders populated detail fields + external source link', async () => {
    const spy = dispatchFetch(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderAt('/reports/42')

    await waitFor(() =>
      expect(screen.getByTestId('report-detail-page')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('report-detail-page')).toHaveAttribute(
      'data-report-id',
      '42',
    )
    expect(
      screen.getByText('Lazarus targets South Korean crypto exchanges'),
    ).toBeInTheDocument()
    expect(screen.getByText('Mandiant')).toBeInTheDocument()
    expect(screen.getByText('2026-03-15')).toBeInTheDocument()
    expect(screen.getByText('TLP:WHITE')).toBeInTheDocument()
    expect(screen.getByText('ransomware, finance')).toBeInTheDocument()
    // External source URL preserved on the detail page — removal
    // from the dashboard ReportFeed row moved the external-link
    // affordance here. `target=_blank` + `rel=noreferrer`.
    const external = screen.getByTestId('report-detail-external')
    expect(external).toHaveAttribute('href', HAPPY_BODY.url)
    expect(external).toHaveAttribute('target', '_blank')
    expect(external).toHaveAttribute('rel', 'noreferrer')

    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/reports/42')
  })

  // D11 — linked_incidents summaries link to /incidents/:id.
  it('renders linked_incidents with Links to /incidents/:id (D11)', async () => {
    dispatchFetch(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderAt('/reports/42')

    await waitFor(() =>
      expect(
        screen.getByTestId('report-detail-linked-incidents'),
      ).toBeInTheDocument(),
    )
    const row = screen.getByTestId('report-detail-linked-incident-18')
    expect(row).toHaveAttribute('data-incident-id', '18')
    const link = row.querySelector('a')
    expect(link).not.toBeNull()
    expect(link!.getAttribute('href')).toBe('/incidents/18')
    expect(link!.textContent).toContain('Axie Infinity Ronin')
  })

  it('does not render linked_incidents section when empty', async () => {
    dispatchFetch(
      new Response(
        JSON.stringify({ ...HAPPY_BODY, linked_incidents: [] }),
        { status: 200 },
      ),
    )
    renderAt('/reports/42')
    await waitFor(() =>
      expect(screen.getByTestId('report-detail-page')).toBeInTheDocument(),
    )
    expect(
      screen.queryByTestId('report-detail-linked-incidents'),
    ).not.toBeInTheDocument()
  })

  it('404 response renders NotFound panel (no retry button)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('not found', { status: 404 }),
    )
    renderAt('/reports/9999')
    await waitFor(() =>
      expect(screen.getByTestId('report-detail-notfound')).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('report-detail-error')).not.toBeInTheDocument()
  })

  it('500 response renders error panel with retry button', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    renderAt('/reports/42')
    await waitFor(() =>
      expect(screen.getByTestId('report-detail-error')).toBeInTheDocument(),
    )
    expect(
      screen.getByTestId('report-detail-error-retry'),
    ).toBeInTheDocument()
  })

  it('malformed path param (non-numeric) renders NotFound without fetching', async () => {
    const spy = dispatchFetch(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderAt('/reports/abc')
    expect(screen.getByTestId('report-detail-notfound')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 20))
    expect(spy).not.toHaveBeenCalled()
  })

  it('zero id renders NotFound without fetching', async () => {
    const spy = dispatchFetch(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderAt('/reports/0')
    expect(screen.getByTestId('report-detail-notfound')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 20))
    expect(spy).not.toHaveBeenCalled()
  })

  // PR #14 Group F — SimilarReportsPanel mounts at the bottom of
  // the detail page, keyed on report.id. The panel fires its own
  // /similar fetch after the detail query resolves.
  it('mounts SimilarReportsPanel with report.id after detail loads (Group F)', async () => {
    const spy = dispatchFetch(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderAt('/reports/42')

    await waitFor(() =>
      expect(screen.getByTestId('report-detail-page')).toBeInTheDocument(),
    )
    // Default dispatchFetch returns `{items: []}` (D10 empty contract)
    // for /similar, so the panel renders its empty-state card.
    await waitFor(() =>
      expect(screen.getByTestId('similar-reports-empty')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('similar-reports-empty')).toHaveAttribute(
      'data-source-report-id',
      '42',
    )
    // Two fetches fire: first the detail endpoint, then the similar
    // endpoint (panel mounts only after detail resolves).
    const similarCalls = spy.mock.calls.filter(([input]) =>
      String(input).endsWith('/similar?k=10'),
    )
    expect(similarCalls).toHaveLength(1)
  })

  // Panel renders populated state when /similar returns rows.
  it('panel renders populated similar-reports with Links (Group F)', async () => {
    const similarBody = {
      items: [
        {
          report: {
            id: 99,
            title: 'Related Lazarus campaign',
            url: 'https://mandiant.com/blog/lazarus-2025q4',
            published: '2025-12-01',
            source_name: 'Mandiant',
          },
          score: 0.87,
        },
      ],
    }
    dispatchFetch(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
      new Response(JSON.stringify(similarBody), { status: 200 }),
    )
    renderAt('/reports/42')

    await waitFor(() =>
      expect(screen.getByTestId('similar-reports')).toBeInTheDocument(),
    )
    const row = screen.getByTestId('similar-reports-item-99')
    const link = row.querySelector('a')
    expect(link!.getAttribute('href')).toBe('/reports/99')
  })
})

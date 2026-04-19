import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { ReportFeed } from '../ReportFeed'

const POPULATED_BODY = {
  items: [
    {
      id: 101,
      title: 'Lazarus deploys new cryptocurrency exchange hijack',
      url: 'https://example.test/r/101',
      url_canonical: 'https://example.test/r/101',
      published: '2026-04-17',
      source_name: 'Example Intel',
      lang: 'en',
    },
    {
      id: 102,
      title: 'Kimsuky phishing against ROK ministries',
      url: 'https://example.test/r/102',
      url_canonical: 'https://example.test/r/102',
      published: '2026-04-16',
      source_name: null,
      lang: 'ko',
    },
  ],
  next_cursor: 'next-abc',
}

const EMPTY_BODY = { items: [], next_cursor: null }

function makeWrapper() {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    // MemoryRouter is required because ReportFeed rows use
    // <Link to="/reports/:id"> per PR #14 D11 cross-link.
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    )
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

afterEach(() => vi.restoreAllMocks())

describe('ReportFeed — 4 render states', () => {
  it('loading state', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<ReportFeed />, { wrapper: Wrapper })
    expect(screen.getByTestId('report-feed-loading')).toBeInTheDocument()
  })

  it('error state with retry', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<ReportFeed />, { wrapper: Wrapper })
    expect(await screen.findByTestId('report-feed-error')).toBeInTheDocument()
    expect(screen.getByTestId('report-feed-retry')).toBeInTheDocument()
  })

  it('empty state when items array is empty', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(EMPTY_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    render(<ReportFeed />, { wrapper: Wrapper })
    expect(await screen.findByTestId('report-feed-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('report-feed')).not.toBeInTheDocument()
  })

  it('populated state preserves BE ordering and renders required fields', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(POPULATED_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    render(<ReportFeed />, { wrapper: Wrapper })
    expect(await screen.findByTestId('report-feed')).toBeInTheDocument()
    const rows = screen.getAllByTestId(/^report-feed-item-/)
    expect(rows).toHaveLength(2)
    // Ordering preserved from BE keyset (newest first).
    expect(rows[0]).toHaveAttribute('data-report-id', '101')
    expect(rows[1]).toHaveAttribute('data-report-id', '102')
    // Title + published + source rendered.
    expect(screen.getByText('Lazarus deploys new cryptocurrency exchange hijack')).toBeInTheDocument()
    expect(screen.getByText('2026-04-17')).toBeInTheDocument()
    expect(screen.getByText('Example Intel')).toBeInTheDocument()
    // Null source_name falls back to dash — no crash.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  // PR #14 D11 cross-link — row title navigates to the internal
  // detail page (`/reports/:id`), NOT the external BE `report.url`.
  // The external URL is reachable from `ReportDetailPage`'s
  // "Source" field.
  it('row title links to /reports/:id (D11 cross-link)', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(POPULATED_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    render(<ReportFeed />, { wrapper: Wrapper })
    expect(await screen.findByTestId('report-feed')).toBeInTheDocument()

    const row101 = screen.getByTestId('report-feed-item-101')
    const link = row101.querySelector('a')
    expect(link).not.toBeNull()
    expect(link!.getAttribute('href')).toBe('/reports/101')
    // React Router's <Link> renders without target=_blank — the
    // navigation stays in-app. The external URL from the PR #13
    // behavior is NOT wired on this element anymore.
    expect(link!.getAttribute('target')).not.toBe('_blank')
    expect(link!.getAttribute('href')).not.toContain('example.test')
  })
})

describe('ReportFeed — PR #12 useReportsList contract preservation', () => {
  it('calls /api/v1/reports with limit=5, no cursor, no group/tlp params', async () => {
    const spy = vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(POPULATED_BODY), { status: 200 })),
    )
    const { Wrapper } = makeWrapper()
    render(<ReportFeed />, { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/reports')
    expect(url.searchParams.get('limit')).toBe('5')
    // Feed never drives pagination — cursor must be absent.
    expect(url.searchParams.has('cursor')).toBe(false)
    // PR #12 useReportsList doesn't emit group_id / tlp by design.
    expect(url.searchParams.has('group_id')).toBe(false)
    expect(url.searchParams.has('tlp')).toBe(false)
  })

  it('date-range filter flows through from store (no hook-signature change)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(POPULATED_BODY), { status: 200 })),
    )
    useFilterStore.setState({
      dateFrom: '2026-01-01',
      dateTo: '2026-04-18',
      groupIds: [],
      tlpLevels: [],
    })
    const { Wrapper } = makeWrapper()
    render(<ReportFeed />, { wrapper: Wrapper })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.searchParams.get('date_from')).toBe('2026-01-01')
    expect(url.searchParams.get('date_to')).toBe('2026-04-18')
  })
})

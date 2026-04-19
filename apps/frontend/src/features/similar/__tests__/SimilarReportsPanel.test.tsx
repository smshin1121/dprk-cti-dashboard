import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { SimilarReportsPanel } from '../SimilarReportsPanel'

const POPULATED_BODY = {
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
    {
      report: {
        id: 101,
        title: 'Different neighbor',
        url: 'https://example.test/r/101',
        published: '2025-11-15',
        source_name: null,
      },
      score: 0.62,
    },
  ],
}

// D10 empty-contract response — source has NULL embedding OR kNN
// returned zero rows. 200 + {items: []}. NOT an error.
const EMPTY_BODY = { items: [] }

function makeWrapper() {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }
  return { client, Wrapper }
}

afterEach(() => vi.restoreAllMocks())

describe('SimilarReportsPanel', () => {
  it('renders loading skeleton while fetch is pending', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<SimilarReportsPanel reportId={42} />, { wrapper: Wrapper })
    expect(screen.getByTestId('similar-reports-loading')).toBeInTheDocument()
  })

  it('renders error state with retry button on 5xx', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<SimilarReportsPanel reportId={42} />, { wrapper: Wrapper })
    expect(
      await screen.findByTestId('similar-reports-error'),
    ).toBeInTheDocument()
    expect(screen.getByTestId('similar-reports-retry')).toBeInTheDocument()
  })

  // D10 empty is a distinct state: the fetch SUCCEEDED with
  // `{items: []}`, and the panel renders an honest empty card.
  // This test pins the no-fake-fallback invariant at the render
  // layer: NO row elements, NO placeholder "recent N" items, NO
  // error state — explicitly `similar-reports-empty` only.
  it('renders the D10 empty state card (no fake fallback) when items=[]', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<SimilarReportsPanel reportId={42} />, { wrapper: Wrapper })

    const empty = await screen.findByTestId('similar-reports-empty')
    expect(empty).toBeInTheDocument()
    expect(empty).toHaveAttribute('data-source-report-id', '42')
    // Positive assertion — no rows rendered.
    expect(screen.queryAllByTestId(/^similar-reports-item-/)).toHaveLength(0)
    // Populated + error panels never render on this path.
    expect(screen.queryByTestId('similar-reports')).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('similar-reports-error'),
    ).not.toBeInTheDocument()
  })

  it('renders populated items with Link to /reports/:id', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<SimilarReportsPanel reportId={42} />, { wrapper: Wrapper })

    await waitFor(() =>
      expect(screen.getByTestId('similar-reports')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('similar-reports')).toHaveAttribute(
      'data-source-report-id',
      '42',
    )

    const rows = screen.getAllByTestId(/^similar-reports-item-/)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveAttribute('data-report-id', '99')
    expect(rows[1]).toHaveAttribute('data-report-id', '101')

    // D11 navigation — row title links to /reports/:id.
    const row99Link = rows[0].querySelector('a')
    expect(row99Link).not.toBeNull()
    expect(row99Link!.getAttribute('href')).toBe('/reports/99')
    expect(row99Link!.getAttribute('target')).not.toBe('_blank')
    expect(row99Link!.textContent).toContain('Related Lazarus campaign')

    // Null source_name falls back to dash (no crash).
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  })

  it('renders scores as compact percentages', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<SimilarReportsPanel reportId={42} />, { wrapper: Wrapper })

    await waitFor(() =>
      expect(screen.getByTestId('similar-reports')).toBeInTheDocument(),
    )
    // 0.87 → "87%", 0.62 → "62%".
    expect(screen.getByTestId('similar-reports-score-99')).toHaveTextContent(
      '87%',
    )
    expect(screen.getByTestId('similar-reports-score-101')).toHaveTextContent(
      '62%',
    )
  })

  // Source-report change opens a new cache scope — mirrors the BE
  // Redis key `similar_reports:{id}:{k}`.
  it('reportId change DOES trigger a refetch (new cache scope)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    const { rerender } = render(<SimilarReportsPanel reportId={42} />, {
      wrapper: Wrapper,
    })
    await waitFor(() =>
      expect(screen.getByTestId('similar-reports')).toBeInTheDocument(),
    )
    expect(spy).toHaveBeenCalledTimes(1)

    rerender(<SimilarReportsPanel reportId={43} />)
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    const url2 = new URL(String(spy.mock.calls[1][0]))
    expect(url2.pathname).toBe('/api/v1/reports/43/similar')
  })

  it('does not fetch when reportId is not a positive integer', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<SimilarReportsPanel reportId={0} />, { wrapper: Wrapper })
    render(<SimilarReportsPanel reportId={-1} />, { wrapper: Wrapper })
    render(<SimilarReportsPanel reportId={Number.NaN} />, {
      wrapper: Wrapper,
    })
    await new Promise((r) => setTimeout(r, 20))
    expect(spy).not.toHaveBeenCalled()
  })
})

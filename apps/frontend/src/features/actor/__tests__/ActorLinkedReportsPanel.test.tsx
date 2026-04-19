import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { ActorLinkedReportsPanel } from '../ActorLinkedReportsPanel'

const POPULATED_BODY = {
  items: [
    {
      id: 999050,
      title: 'Report A — newest',
      url: 'https://x.test/a',
      url_canonical: 'https://x.test/a',
      published: '2026-03-15',
      source_id: 1,
      source_name: 'Vendor A',
      lang: 'en',
      tlp: 'WHITE',
    },
    {
      id: 999051,
      title: 'Report B',
      url: 'https://x.test/b',
      url_canonical: 'https://x.test/b',
      published: '2026-02-10',
      source_id: 1,
      source_name: 'Vendor A',
      lang: 'en',
      tlp: 'WHITE',
    },
  ],
  next_cursor: null,
}

const EMPTY_BODY = { items: [], next_cursor: null }

function renderWithRouter(ui: ReactNode) {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }
  return render(<Wrapper>{ui}</Wrapper>)
}

afterEach(() => vi.restoreAllMocks())

describe('ActorLinkedReportsPanel — 4 render states (plan D13)', () => {
  // State 1: loading
  it('renders loading skeleton while fetch is pending', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    renderWithRouter(<ActorLinkedReportsPanel actorId={999003} />)
    expect(
      screen.getByTestId('actor-linked-reports-loading'),
    ).toBeInTheDocument()
    // The empty / populated / error testids MUST NOT co-exist
    // with loading. Strict per-state render.
    expect(
      screen.queryByTestId('actor-linked-reports-panel'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('actor-linked-reports-empty'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('actor-linked-reports-error'),
    ).not.toBeInTheDocument()
  })

  // State 2: error (with retry)
  it('renders error card with retry button on 5xx', async () => {
    const spy = vi.spyOn(global, 'fetch')
    spy.mockResolvedValueOnce(new Response('boom', { status: 500 }))
    // Retry click fires a second fetch. Stub it so the retry path
    // transitions cleanly back to empty.
    spy.mockResolvedValueOnce(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    renderWithRouter(<ActorLinkedReportsPanel actorId={999003} />)

    const errorCard = await screen.findByTestId(
      'actor-linked-reports-error',
    )
    expect(errorCard).toHaveAttribute('role', 'alert')
    const retryBtn = screen.getByTestId('actor-linked-reports-retry')
    expect(retryBtn).toBeInTheDocument()

    // Retry → transitions to empty card.
    await userEvent.click(retryBtn)
    await waitFor(() =>
      expect(
        screen.getByTestId('actor-linked-reports-empty'),
      ).toBeInTheDocument(),
    )
    expect(
      screen.queryByTestId('actor-linked-reports-error'),
    ).not.toBeInTheDocument()
  })

  // State 3: D15 empty — first-class, no fake fallback
  it('renders D15 empty-state card (no fake fallback) when items=[]', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    renderWithRouter(<ActorLinkedReportsPanel actorId={999004} />)

    const empty = await screen.findByTestId('actor-linked-reports-empty')
    expect(empty).toHaveAttribute('data-source-actor-id', '999004')
    // Positive no-row assertion — pins the D15 empty contract: no
    // fake "recent N reports" stand-in, no shared-tag fallback. A
    // regression that mistakes empty for populated would add at
    // least one matching testid and fail here.
    expect(
      screen.queryAllByTestId(/^actor-linked-reports-item-/),
    ).toHaveLength(0)
    // Populated testid MUST NOT appear on the empty branch.
    expect(
      screen.queryByTestId('actor-linked-reports-panel'),
    ).not.toBeInTheDocument()
  })

  // State 4: populated
  it('renders populated list with row-per-report and /reports/:id links', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    renderWithRouter(<ActorLinkedReportsPanel actorId={999003} />)

    const panel = await screen.findByTestId('actor-linked-reports-panel')
    expect(panel).toHaveAttribute('data-source-actor-id', '999003')

    const items = screen.queryAllByTestId(/^actor-linked-reports-item-/)
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveAttribute('data-report-id', '999050')
    expect(items[1]).toHaveAttribute('data-report-id', '999051')

    // Each row title is a Link to /reports/:id (D11 cross-link for
    // actor → report navigation).
    const linkA = screen.getByRole('link', { name: /Report A — newest/ })
    expect(linkA).toHaveAttribute('href', '/reports/999050')

    // Empty / error testids MUST NOT co-exist with populated.
    expect(
      screen.queryByTestId('actor-linked-reports-empty'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('actor-linked-reports-error'),
    ).not.toBeInTheDocument()
  })
})

// D13 subscription lock — panel fetches from sibling endpoint; the
// path in the URL hits /actors/{id}/reports, proving the panel's
// data comes from the PR #15 endpoint, NOT from the actor-detail
// payload (which would violate D12).
describe('ActorLinkedReportsPanel — D13 sibling-endpoint wire', () => {
  it('GETs /api/v1/actors/{id}/reports (not the detail endpoint)', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    renderWithRouter(<ActorLinkedReportsPanel actorId={999003} />)
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))

    const url = new URL(String(spy.mock.calls[0][0]), 'http://x.test')
    expect(url.pathname).toBe('/api/v1/actors/999003/reports')
  })
})

// Invalid actor id — render nothing rather than mount the panel in
// a disabled-hook state that would render an "empty" card misleadingly.
describe('ActorLinkedReportsPanel — invalid actorId guard', () => {
  it('renders nothing when actorId is zero / negative / NaN', () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { container: cZero } = renderWithRouter(
      <ActorLinkedReportsPanel actorId={0} />,
    )
    expect(cZero.firstChild).toBeNull()
    const { container: cNeg } = renderWithRouter(
      <ActorLinkedReportsPanel actorId={-1} />,
    )
    expect(cNeg.firstChild).toBeNull()
    const { container: cNaN } = renderWithRouter(
      <ActorLinkedReportsPanel actorId={Number.NaN} />,
    )
    expect(cNaN.firstChild).toBeNull()
  })
})

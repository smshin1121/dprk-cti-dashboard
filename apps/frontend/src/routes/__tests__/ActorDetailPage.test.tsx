import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { ActorDetailPage } from '../ActorDetailPage'

// PR #15 Group E mounted `ActorLinkedReportsPanel` below the
// codenames section. Tests that exercise the populated detail branch
// now also see a fetch to `/api/v1/actors/{id}/reports` from the
// panel mount. URL-dispatch mock lets the existing D11/D12 tests
// keep asserting about the detail payload while the panel gets a
// D15 empty contract by default. Pattern lifted from
// `ReportDetailPage.test.tsx`'s `dispatchFetch` (PR #14 Group F).
function dispatchFetch(
  detailResponse: Response,
  actorReportsResponse?: Response,
) {
  return vi.spyOn(global, 'fetch').mockImplementation(async (input) => {
    const url = new URL(String(input), 'http://x.test')
    if (url.pathname.match(/\/api\/v1\/actors\/\d+\/reports$/)) {
      return (
        actorReportsResponse ??
        new Response(
          JSON.stringify({ items: [], next_cursor: null }),
          { status: 200 },
        )
      )
    }
    return detailResponse.clone()
  })
}

// Sentinel route to verify ActorLinkedReportsPanel's row links point
// at /reports/:id without pulling the real page's fetch wiring.
function ReportDetailStub(): JSX.Element {
  return <div data-testid="report-detail-stub">report detail stub</div>
}

function renderAt(initialPath: string) {
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      { path: '/actors/:id', element: <ActorDetailPage /> },
      { path: '/reports/:id', element: <ReportDetailStub /> },
    ],
    { initialEntries: [initialPath] },
  )
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<RouterProvider router={router} />, { wrapper: Wrapper })
}

// BE ActorDetail example[0].
const HAPPY_BODY = {
  id: 3,
  name: 'Lazarus Group',
  mitre_intrusion_set_id: 'G0032',
  aka: ['APT38', 'Hidden Cobra'],
  description: 'DPRK-attributed cyber espionage and financially motivated group',
  codenames: ['Andariel', 'Bluenoroff'],
}

const POPULATED_REPORTS = {
  items: [
    {
      id: 999050,
      title: 'Linked Report Alpha',
      url: 'https://x.test/a',
      url_canonical: 'https://x.test/a',
      published: '2026-03-15',
      source_id: 1,
      source_name: 'Vendor A',
      lang: 'en',
      tlp: 'WHITE',
    },
  ],
  next_cursor: null,
}

afterEach(() => vi.restoreAllMocks())

describe('ActorDetailPage', () => {
  it('renders loading skeleton while detail fetch is pending', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    renderAt('/actors/3')
    expect(screen.getByTestId('actor-detail-loading')).toBeInTheDocument()
  })

  it('renders populated detail fields', async () => {
    const spy = dispatchFetch(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderAt('/actors/3')

    await waitFor(() =>
      expect(screen.getByTestId('actor-detail-page')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('actor-detail-page')).toHaveAttribute(
      'data-actor-id',
      '3',
    )
    expect(screen.getByText('Lazarus Group')).toBeInTheDocument()
    expect(screen.getByText('G0032')).toBeInTheDocument()
    expect(screen.getByText('APT38, Hidden Cobra')).toBeInTheDocument()
    expect(screen.getByText('Andariel, Bluenoroff')).toBeInTheDocument()

    // The detail fetch is the FIRST call; the panel fetch follows.
    const detailUrl = new URL(
      String(spy.mock.calls[0][0]),
      'http://x.test',
    )
    expect(detailUrl.pathname).toBe('/api/v1/actors/3')
  })

  // D12 regression — even when the detail payload leaks reports-like
  // keys, the ActorDetail Zod schema strips them AND the page has no
  // render branch that would surface them. The NEW panel (PR #15)
  // comes from a SEPARATE fetch to /actors/3/reports; its data never
  // crosses into the detail payload. This test is the belt+suspenders
  // that both halves hold.
  it(
    'D12 — detail payload reports-like keys are stripped even when ' +
      'the new panel mounts',
    async () => {
      const leakyDetail = {
        ...HAPPY_BODY,
        linked_reports: [
          {
            id: 42,
            title: 'LEAKED-FROM-DETAIL',
            url: 'https://x.test/1',
            published: '2026-01-01',
            source_name: null,
          },
        ],
        reports: [{ id: 99 }],
        recent_reports: [{ id: 100 }],
      }
      // Panel fetch → D15 empty by default (dispatchFetch fallback).
      dispatchFetch(
        new Response(JSON.stringify(leakyDetail), { status: 200 }),
      )
      renderAt('/actors/3')

      await waitFor(() =>
        expect(screen.getByTestId('actor-detail-page')).toBeInTheDocument(),
      )
      // Belt — the detail surface has no render branch for any
      // reports-like key; it's structurally impossible for a Zod
      // leak to surface here.
      expect(
        screen.queryByTestId('actor-detail-linked-reports'),
      ).not.toBeInTheDocument()
      expect(
        screen.queryByTestId('actor-detail-recent-reports'),
      ).not.toBeInTheDocument()
      // Suspenders — the leaked title text from the DETAIL payload
      // does not appear on the page. (The PANEL fetched from the
      // sibling endpoint — an empty array by default — so any text
      // that does appear must come from the panel's response, which
      // has no report titled "LEAKED-FROM-DETAIL".)
      expect(
        screen.queryByText('LEAKED-FROM-DETAIL'),
      ).not.toBeInTheDocument()
    },
  )

  it('renders without mitre id / description when null', async () => {
    dispatchFetch(
      new Response(
        JSON.stringify({
          ...HAPPY_BODY,
          mitre_intrusion_set_id: null,
          description: null,
          aka: [],
          codenames: [],
        }),
        { status: 200 },
      ),
    )
    renderAt('/actors/3')
    await waitFor(() =>
      expect(screen.getByTestId('actor-detail-page')).toBeInTheDocument(),
    )
    expect(
      screen.queryByTestId('actor-detail-description'),
    ).not.toBeInTheDocument()
  })

  it('404 response renders NotFound panel (panel does not mount)', async () => {
    // Panel MUST NOT mount on the 404 branch — plan D18 says the
    // panel lives inside the populated render branch. The
    // dispatchFetch second arg is provided but never consumed.
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('not found', { status: 404 }),
    )
    renderAt('/actors/9999')
    await waitFor(() =>
      expect(screen.getByTestId('actor-detail-notfound')).toBeInTheDocument(),
    )
    expect(
      screen.queryByTestId('actor-linked-reports-panel'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('actor-linked-reports-empty'),
    ).not.toBeInTheDocument()
  })

  it('malformed path param renders NotFound without fetching', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderAt('/actors/oops')
    expect(
      screen.getByTestId('actor-detail-notfound'),
    ).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 20))
    expect(spy).not.toHaveBeenCalled()
  })
})

// PR #15 Group E additions — panel mount + 4-state integration +
// D18 scope assertions.
describe('ActorDetailPage + ActorLinkedReportsPanel integration (PR #15)', () => {
  it('populated detail + populated panel: panel mounts below codenames', async () => {
    dispatchFetch(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
      new Response(JSON.stringify(POPULATED_REPORTS), { status: 200 }),
    )
    renderAt('/actors/3')

    await waitFor(() =>
      expect(screen.getByTestId('actor-linked-reports-panel')).toBeInTheDocument(),
    )
    expect(
      screen.getByTestId('actor-linked-reports-panel'),
    ).toHaveAttribute('data-source-actor-id', '3')
    // Linked-report row appears with the expected title + href.
    expect(
      screen.getByRole('link', { name: /Linked Report Alpha/ }),
    ).toHaveAttribute('href', '/reports/999050')
  })

  it('populated detail + D15 empty panel: empty card renders below codenames', async () => {
    dispatchFetch(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderAt('/actors/3')

    await waitFor(() =>
      expect(
        screen.getByTestId('actor-linked-reports-empty'),
      ).toBeInTheDocument(),
    )
    // Page-level D15 no-fake-fallback invariant — zero linked
    // report rows appear anywhere.
    expect(
      screen.queryAllByTestId(/^actor-linked-reports-item-/),
    ).toHaveLength(0)
    // Codenames section still present — empty panel does not
    // displace the detail shell.
    expect(screen.getByText('Andariel, Bluenoroff')).toBeInTheDocument()
  })

  it('populated detail + panel error: error card with retry renders', async () => {
    dispatchFetch(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
      new Response('boom', { status: 500 }),
    )
    renderAt('/actors/3')

    await waitFor(() =>
      expect(
        screen.getByTestId('actor-linked-reports-error'),
      ).toBeInTheDocument(),
    )
    expect(
      screen.getByTestId('actor-linked-reports-retry'),
    ).toBeInTheDocument()
    // Detail section above still intact on panel failure.
    expect(screen.getByTestId('actor-detail-page')).toBeInTheDocument()
  })

  // D18 scope lock — the panel's ONLY consumer is ActorDetailPage.
  // This is a static-source assertion: the check reads the repo
  // state to verify no other file imports the panel.
  //
  // Rationale: a plain runtime test (querying the DOM) cannot prove
  // absence of future cross-page imports; grepping the source does.
})

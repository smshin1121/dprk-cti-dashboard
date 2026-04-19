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

function renderAt(initialPath: string) {
  const client = createQueryClient()
  const router = createMemoryRouter(
    [{ path: '/actors/:id', element: <ActorDetailPage /> }],
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

afterEach(() => vi.restoreAllMocks())

describe('ActorDetailPage', () => {
  it('renders loading skeleton while fetch is pending', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    renderAt('/actors/3')
    expect(screen.getByTestId('actor-detail-loading')).toBeInTheDocument()
  })

  it('renders populated detail fields', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
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

    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/actors/3')
  })

  // D11 out-of-scope pin — the page renders ZERO reports surface.
  // Even if a BE leak ships linked_reports / reports / recent_reports,
  // the Zod schema strips them (see schemas.test.ts) AND this page
  // has no render branch that would surface them. Belt + suspenders.
  it('renders no reports-like section even if BE payload leaks such keys (D11)', async () => {
    const leakyBody = {
      ...HAPPY_BODY,
      linked_reports: [
        {
          id: 42,
          title: 'leaked',
          url: 'https://x.test/1',
          published: '2026-01-01',
          source_name: null,
        },
      ],
      reports: [{ id: 99 }],
      recent_reports: [{ id: 100 }],
    }
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(leakyBody), { status: 200 }),
    )
    renderAt('/actors/3')

    await waitFor(() =>
      expect(screen.getByTestId('actor-detail-page')).toBeInTheDocument(),
    )
    // No reports-ish DOM present anywhere on the page.
    expect(
      screen.queryByTestId('actor-detail-linked-reports'),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByTestId('actor-detail-recent-reports'),
    ).not.toBeInTheDocument()
    // Leaked title text does not appear.
    expect(screen.queryByText('leaked')).not.toBeInTheDocument()
  })

  it('renders without mitre id / description when null', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
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

  it('404 response renders NotFound panel', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('not found', { status: 404 }),
    )
    renderAt('/actors/9999')
    await waitFor(() =>
      expect(screen.getByTestId('actor-detail-notfound')).toBeInTheDocument(),
    )
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

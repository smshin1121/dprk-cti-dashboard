import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { WorldMap } from '../WorldMap'

const HAPPY_BODY = {
  countries: [
    { iso2: 'KR', count: 18 },
    { iso2: 'US', count: 9 },
    { iso2: 'KP', count: 2 },
  ],
}

const EMPTY_BODY = { countries: [] }

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

describe('WorldMap — 4 render states', () => {
  it('shows loading skeleton on initial fetch', () => {
    // Mock fetch that never resolves so query stays in loading state.
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<WorldMap />, { wrapper: Wrapper })

    expect(screen.getByTestId('world-map-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('world-map')).not.toBeInTheDocument()
  })

  it('shows error card + retry button on fetch failure', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('{"detail": "boom"}', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<WorldMap />, { wrapper: Wrapper })

    expect(await screen.findByTestId('world-map-error')).toBeInTheDocument()
    expect(screen.getByTestId('world-map-retry')).toBeInTheDocument()
  })

  it('renders the map and overlays empty-state message when response has no countries', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<WorldMap />, { wrapper: Wrapper })

    // Plan D8 pattern carried to the map: keep the map visible so
    // the viz doesn't wobble on filter changes; overlay copy
    // explains the empty state.
    expect(await screen.findByTestId('world-map')).toBeInTheDocument()
    expect(screen.getByTestId('world-map-empty')).toBeInTheDocument()
  })

  it('renders populated map with country fill keyed off the BE payload', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<WorldMap />, { wrapper: Wrapper })

    await waitFor(() =>
      expect(screen.getByTestId('world-map-features')).toBeInTheDocument(),
    )
    // Empty overlay should be gone when data is present.
    expect(screen.queryByTestId('world-map-empty')).not.toBeInTheDocument()
  })
})

describe('WorldMap — DPRK highlight invariant (plan D7)', () => {
  it('DPRK feature carries data-dprk="true" even when BE response has NO KP row', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ countries: [{ iso2: 'US', count: 3 }] }),
        { status: 200 },
      ),
    )
    const { Wrapper } = makeWrapper()
    render(<WorldMap />, { wrapper: Wrapper })

    // DPRK's ISO numeric is 408 — feature presence + highlight are
    // geographic identity, not driven by the BE payload. This pins
    // plan D7: the BE treats KP as a plain country row, the FE owns
    // the highlight, and the highlight is always applied.
    const dprk = await screen.findByTestId('world-map-country-408')
    expect(dprk).toHaveAttribute('data-dprk', 'true')
    expect(dprk).toHaveAttribute('data-iso2', 'KP')
    // Centroid marker overlay is also applied regardless of data.
    expect(screen.getByTestId('world-map-dprk-marker')).toBeInTheDocument()
  })

  it('DPRK count reflects BE payload like any other country (no special-case)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<WorldMap />, { wrapper: Wrapper })

    const dprk = await screen.findByTestId('world-map-country-408')
    // KP in HAPPY_BODY = 2. Same data-count read path as any other
    // country — no BE special-case (plan D2 + D7 lock).
    expect(dprk).toHaveAttribute('data-count', '2')

    // Non-DPRK countries should NOT carry the dprk flag.
    const kr = screen.getByTestId('world-map-country-410') // ISO numeric for KR
    expect(kr).not.toHaveAttribute('data-dprk')
    expect(kr).toHaveAttribute('data-iso2', 'KR')
    expect(kr).toHaveAttribute('data-count', '18')
  })

  it('DPRK highlight renders identically when KP count is zero', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ countries: [{ iso2: 'KP', count: 0 }] }),
        { status: 200 },
      ),
    )
    const { Wrapper } = makeWrapper()
    render(<WorldMap />, { wrapper: Wrapper })

    const dprk = await screen.findByTestId('world-map-country-408')
    expect(dprk).toHaveAttribute('data-dprk', 'true')
    expect(dprk).toHaveAttribute('data-count', '0')
    expect(screen.getByTestId('world-map-dprk-marker')).toBeInTheDocument()
  })
})

describe('WorldMap — tooltip via <title>', () => {
  it('each country path carries a <title> with iso2 + count for native hover tooltip', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<WorldMap />, { wrapper: Wrapper })

    const kr = await screen.findByTestId('world-map-country-410')
    const title = within(kr).getByText('KR: 18', { selector: 'title' })
    expect(title).toBeInTheDocument()
  })
})

import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import {
  AttackHeatmap,
  DEFAULT_TOP_N,
  EXPANDED_TOP_N,
} from '../AttackHeatmap'

const POPULATED_BODY = {
  tactics: [
    { id: 'TA0001', name: 'TA0001' },
    { id: 'TA0002', name: 'TA0002' },
  ],
  rows: [
    {
      tactic_id: 'TA0001',
      techniques: [
        { technique_id: 'T1566', count: 18 },
        { technique_id: 'T1190', count: 7 },
      ],
    },
    {
      tactic_id: 'TA0002',
      techniques: [{ technique_id: 'T1059', count: 12 }],
    },
  ],
}

const EMPTY_BODY = { tactics: [], rows: [] }

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

describe('AttackHeatmap — top_n contract (plan D8)', () => {
  it('DEFAULT_TOP_N is locked at 30', () => {
    // This is the plan D8 contract. If the constant ever bumps,
    // review the plan + FE agreement first.
    expect(DEFAULT_TOP_N).toBe(30)
  })

  it('EXPANDED_TOP_N matches the BE upper bound (200)', () => {
    // Matches Query(le=200) on services/api/src/api/routers/
    // analytics.py — keeping them in lockstep avoids a 422 on the
    // expand click when the BE rejects a higher value.
    expect(EXPANDED_TOP_N).toBe(200)
  })

  it('initial mount requests top_n=30 in the URL', async () => {
    const spy = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<AttackHeatmap />, { wrapper: Wrapper })

    await waitFor(() => expect(spy).toHaveBeenCalled())
    const url = new URL(String(spy.mock.calls[0][0]))
    expect(url.pathname).toBe('/api/v1/analytics/attack_matrix')
    expect(url.searchParams.get('top_n')).toBe('30')
  })

  it('toggling expand flips the URL to top_n=200; toggle back restores 30', async () => {
    // Fresh Response per call — Response bodies are single-consumption
    // streams; mockResolvedValue with one instance would lock after
    // the first fetch.
    const spy = vi.spyOn(global, 'fetch').mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
      ),
    )
    const user = userEvent.setup()
    const { Wrapper } = makeWrapper()
    render(<AttackHeatmap />, { wrapper: Wrapper })

    await waitFor(() =>
      expect(screen.getByTestId('attack-heatmap')).toHaveAttribute(
        'data-top-n',
        '30',
      ),
    )

    await user.click(screen.getByTestId('attack-heatmap-toggle'))
    await waitFor(() =>
      expect(screen.getByTestId('attack-heatmap')).toHaveAttribute(
        'data-top-n',
        '200',
      ),
    )
    const expandCall = spy.mock.calls.find(([u]) =>
      String(u).includes('top_n=200'),
    )
    expect(expandCall).toBeDefined()

    await user.click(screen.getByTestId('attack-heatmap-toggle'))
    await waitFor(() =>
      expect(screen.getByTestId('attack-heatmap')).toHaveAttribute(
        'data-top-n',
        '30',
      ),
    )
  })
})

describe('AttackHeatmap — row-based consumption (plan D2)', () => {
  it('renders rows in the BE-provided order, each with its own techniques', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<AttackHeatmap />, { wrapper: Wrapper })

    await waitFor(() =>
      expect(screen.getByTestId('attack-heatmap-grid')).toBeInTheDocument(),
    )

    // TA0001 first (BE orders rows by total count desc per Group A
    // aggregator), then TA0002.
    const row1 = screen.getByTestId('attack-heatmap-row-TA0001')
    const row2 = screen.getByTestId('attack-heatmap-row-TA0002')
    expect(row1).toBeInTheDocument()
    expect(row2).toBeInTheDocument()
    // TA0001 contains two techniques; TA0002 contains one.
    expect(
      screen.getByTestId('attack-heatmap-cell-TA0001-T1566'),
    ).toHaveAttribute('data-count', '18')
    expect(
      screen.getByTestId('attack-heatmap-cell-TA0001-T1190'),
    ).toHaveAttribute('data-count', '7')
    expect(
      screen.getByTestId('attack-heatmap-cell-TA0002-T1059'),
    ).toHaveAttribute('data-count', '12')
  })

  it('does NOT flatten the matrix to a sparse cells list', async () => {
    // Plan D2 locked the row-based shape because it simplifies FE
    // rendering. If a future edit pre-processes the rows into a
    // flat [(tactic, technique)] array, the per-tactic row testid
    // would disappear. This test fires fast if that happens.
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<AttackHeatmap />, { wrapper: Wrapper })

    await waitFor(() =>
      expect(screen.getByTestId('attack-heatmap-row-TA0001')).toBeInTheDocument(),
    )
    // The presence of distinct per-tactic row testids is the
    // contract. Count matches tactics length.
    const rows = screen.getAllByTestId(/^attack-heatmap-row-/)
    expect(rows).toHaveLength(POPULATED_BODY.rows.length)
  })
})

describe('AttackHeatmap — 4 render states', () => {
  it('loading state', () => {
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    const { Wrapper } = makeWrapper()
    render(<AttackHeatmap />, { wrapper: Wrapper })
    expect(screen.getByTestId('attack-heatmap-loading')).toBeInTheDocument()
  })

  it('error state with retry button', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('boom', { status: 500 }),
    )
    const { Wrapper } = makeWrapper()
    render(<AttackHeatmap />, { wrapper: Wrapper })
    expect(await screen.findByTestId('attack-heatmap-error')).toBeInTheDocument()
    expect(screen.getByTestId('attack-heatmap-retry')).toBeInTheDocument()
  })

  it('empty matrix renders the empty CARD (not a collapsed overlay) per plan D8', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<AttackHeatmap />, { wrapper: Wrapper })

    // Empty CARD present:
    expect(
      await screen.findByTestId('attack-heatmap-empty'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('attack-heatmap-empty-clear-filters'),
    ).toBeInTheDocument()

    // Heatmap grid is ABSENT — plan D8 rejected the "collapsed
    // overlay over a ghost heatmap" pattern. If this fires true,
    // someone reverted to the collapsed-overlay design.
    expect(screen.queryByTestId('attack-heatmap-grid')).not.toBeInTheDocument()
    expect(screen.queryByTestId('attack-heatmap')).not.toBeInTheDocument()
  })

  it('empty-card clear-filters CTA resets the filter store', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    useFilterStore.setState({
      dateFrom: '2026-01-01',
      dateTo: '2026-04-18',
      groupIds: [1, 3],
      tlpLevels: ['AMBER'],
    })
    const user = userEvent.setup()
    const { Wrapper } = makeWrapper()
    render(<AttackHeatmap />, { wrapper: Wrapper })

    await user.click(
      await screen.findByTestId('attack-heatmap-empty-clear-filters'),
    )
    const state = useFilterStore.getState()
    expect(state.dateFrom).toBeNull()
    expect(state.dateTo).toBeNull()
    expect(state.groupIds).toEqual([])
    expect(state.tlpLevels).toEqual([])
  })

  it('populated state renders tactic rows + cells', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(POPULATED_BODY), { status: 200 }),
    )
    const { Wrapper } = makeWrapper()
    render(<AttackHeatmap />, { wrapper: Wrapper })

    expect(await screen.findByTestId('attack-heatmap')).toBeInTheDocument()
    expect(screen.getByTestId('attack-heatmap-grid')).toBeInTheDocument()
    expect(
      screen.queryByTestId('attack-heatmap-empty'),
    ).not.toBeInTheDocument()
  })
})

/**
 * ActorNetworkGraph component tests (PR 3 T4 RED batch).
 *
 * Plan ``docs/plans/actor-network-data.md`` v1.6 §4 T4 + L2 + L4 + L6
 * + L13:
 *
 *   - Populated state: SVG render with **exact** `<circle>` count =
 *     `nodes.length`, **exact** `<line>` count = `edges.length`.
 *     Each node has a testid pattern by kind (`actor:` / `tool:` /
 *     `sector:`), an aria-label, and a kind-specific stroke style.
 *     Degree maps to circle radius (larger nodes for higher degree).
 *   - Empty state: same text-only `Planned · no data yet` block as
 *     the L6 reserved-slot. NO `<svg>` / `<canvas>` / synthetic
 *     skeleton / sparkline marks rendered for any state of the slot.
 *   - Topology-change reseed: swapping props from one populated
 *     graph to a different graph with equal `nodes.length +
 *     edges.length` MUST cause the d3-force `useEffect` to re-run
 *     (positional `<circle>` cx/cy diff or internal counter ref).
 *   - Cap-breach legend: when `cap_breached: true`, the response
 *     surface's tooltip / legend contains a small explainer
 *     (per plan §5 risk row #7).
 *
 * RED state: `ActorNetworkGraph.tsx` placeholder returns `null`. All
 * assertions below fail at T4 commit time. T10 GREEN flips them to
 * PASS.
 *
 * Per `pattern_tdd_stub_for_red_collection`, the placeholder satisfies
 * vitest collection. Per Codex r2 risk anticipation: do not
 * `vi.mock` the component; mock only the hook (`useActorNetwork`).
 */

import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../../lib/queryClient'
import { ActorNetworkGraph } from '../ActorNetworkGraph'

// Mock the hook so each test injects deterministic data without
// hitting the real fetch / store layer. Real hook tests live in
// useActorNetwork.test.tsx (T3).
vi.mock('../../analytics/useActorNetwork', () => ({
  useActorNetwork: vi.fn(),
}))

import { useActorNetwork } from '../../analytics/useActorNetwork'

const POPULATED_DATA = {
  nodes: [
    { id: 'actor:1', kind: 'actor' as const, label: 'Lazarus Group', degree: 6 },
    { id: 'actor:2', kind: 'actor' as const, label: 'Andariel', degree: 3 },
    { id: 'tool:42', kind: 'tool' as const, label: 'Phishing', degree: 2 },
    { id: 'sector:GOV', kind: 'sector' as const, label: 'GOV', degree: 4 },
  ],
  edges: [
    { source_id: 'actor:1', target_id: 'tool:42', weight: 8 },
    { source_id: 'actor:1', target_id: 'sector:GOV', weight: 3 },
    { source_id: 'actor:1', target_id: 'actor:2', weight: 2 },
  ],
  cap_breached: false,
}

const EMPTY_DATA = { nodes: [], edges: [], cap_breached: false }

// Codex r5 M3 fold: POPULATED_DATA above is a 3-edge star centered
// on actor:1. To test topology-change reseed we need a GENUINELY
// different shape (not another star where d3-force's deterministic
// minimum could land at the same coordinates by accident). This
// fixture is a chain: actor:9 — tool:99 — sector:FIN — actor:10.
// Same cardinality (4 nodes / 3 edges) but the connectivity matrix
// is different.
const POPULATED_DATA_DIFFERENT_TOPOLOGY = {
  nodes: [
    { id: 'actor:9', kind: 'actor' as const, label: 'APT38', degree: 1 },
    { id: 'tool:99', kind: 'tool' as const, label: 'Cobalt Strike', degree: 2 },
    { id: 'sector:FIN', kind: 'sector' as const, label: 'FIN', degree: 2 },
    { id: 'actor:10', kind: 'actor' as const, label: 'Andariel-X', degree: 1 },
  ],
  edges: [
    // Chain: actor:9 — tool:99 — sector:FIN — actor:10
    { source_id: 'actor:9', target_id: 'tool:99', weight: 5 },
    { source_id: 'tool:99', target_id: 'sector:FIN', weight: 4 },
    { source_id: 'sector:FIN', target_id: 'actor:10', weight: 2 },
  ],
  cap_breached: false,
}

function makeWrapper() {
  const client = createQueryClient()
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return { Wrapper }
}

function mockHookSuccess(data: typeof POPULATED_DATA | typeof EMPTY_DATA) {
  vi.mocked(useActorNetwork).mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    isSuccess: true,
    error: null,
  } as ReturnType<typeof useActorNetwork>)
}

beforeEach(() => {
  vi.mocked(useActorNetwork).mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ActorNetworkGraph — populated state', () => {
  it('renders exactly nodes.length <circle> elements', async () => {
    mockHookSuccess(POPULATED_DATA)
    const { Wrapper } = makeWrapper()
    const { container } = render(<ActorNetworkGraph />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(container.querySelectorAll('circle')).toHaveLength(
        POPULATED_DATA.nodes.length,
      )
    })
  })

  it('renders exactly edges.length <line> elements', async () => {
    mockHookSuccess(POPULATED_DATA)
    const { Wrapper } = makeWrapper()
    const { container } = render(<ActorNetworkGraph />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(container.querySelectorAll('line')).toHaveLength(
        POPULATED_DATA.edges.length,
      )
    })
  })

  it('exposes one testid per node, prefixed by kind', async () => {
    mockHookSuccess(POPULATED_DATA)
    const { Wrapper } = makeWrapper()
    render(<ActorNetworkGraph />, { wrapper: Wrapper })

    await waitFor(() => {
      // Codex r5 L1 fold: assert testid presence for EVERY node
      // (not just 3 of 4). Node testids follow the kind-prefixed id
      // from the BE DTO (`actor:` / `tool:` / `sector:`) so a future
      // test can target a specific node without depending on cx/cy
      // positions.
      for (const node of POPULATED_DATA.nodes) {
        expect(
          screen.getByTestId(`actor-network-node-${node.id}`),
          `node testid actor-network-node-${node.id} missing`,
        ).toBeInTheDocument()
      }
    })
  })

  it('every node has a non-empty aria-label (a11y)', async () => {
    mockHookSuccess(POPULATED_DATA)
    const { Wrapper } = makeWrapper()
    const { container } = render(<ActorNetworkGraph />, { wrapper: Wrapper })

    await waitFor(() => {
      const nodes = container.querySelectorAll('[data-testid^="actor-network-node-"]')
      expect(nodes.length).toBe(POPULATED_DATA.nodes.length)
      for (const n of nodes) {
        const label = n.getAttribute('aria-label')
        expect(
          label && label.length > 0,
          `node ${n.getAttribute('data-testid')} missing aria-label`,
        ).toBe(true)
      }
    })
  })

  it('higher-degree node has larger radius (degree → r mapping)', async () => {
    mockHookSuccess(POPULATED_DATA)
    const { Wrapper } = makeWrapper()
    const { container } = render(<ActorNetworkGraph />, { wrapper: Wrapper })

    await waitFor(() => {
      // POPULATED_DATA has actor:1 (degree=6) > actor:2 (degree=3).
      // The radius mapping must reflect that ordering.
      const a1 = container.querySelector(
        '[data-testid="actor-network-node-actor:1"] circle',
      ) as SVGCircleElement | null
      const a2 = container.querySelector(
        '[data-testid="actor-network-node-actor:2"] circle',
      ) as SVGCircleElement | null
      expect(a1, 'actor:1 circle missing').toBeTruthy()
      expect(a2, 'actor:2 circle missing').toBeTruthy()
      const r1 = parseFloat(a1!.getAttribute('r') ?? '0')
      const r2 = parseFloat(a2!.getAttribute('r') ?? '0')
      expect(r1).toBeGreaterThan(r2)
    })
  })

  it('kind → distinct stroke style (per DESIGN.md)', async () => {
    mockHookSuccess(POPULATED_DATA)
    const { Wrapper } = makeWrapper()
    const { container } = render(<ActorNetworkGraph />, { wrapper: Wrapper })

    await waitFor(() => {
      // Three kinds → three distinct stroke styles. Codex r5 L2
      // fold: pin the explicit `stroke` attribute (or computed
      // stroke value), NOT a class string — distinct class strings
      // can still resolve to the same rendered stroke colour.
      const actor = container.querySelector(
        '[data-testid="actor-network-node-actor:1"] circle',
      ) as SVGCircleElement | null
      const tool = container.querySelector(
        '[data-testid="actor-network-node-tool:42"] circle',
      ) as SVGCircleElement | null
      const sector = container.querySelector(
        '[data-testid="actor-network-node-sector:GOV"] circle',
      ) as SVGCircleElement | null
      expect(actor, 'actor circle missing').toBeTruthy()
      expect(tool, 'tool circle missing').toBeTruthy()
      expect(sector, 'sector circle missing').toBeTruthy()
      const strokeOf = (el: SVGCircleElement) =>
        el.getAttribute('stroke') ?? ''
      const a = strokeOf(actor!)
      const t = strokeOf(tool!)
      const s = strokeOf(sector!)
      // Each stroke must be a non-empty value AND distinct from the
      // other two. The exact RGB / theme-token values are owned by
      // DESIGN.md; this test pins the distinctness invariant.
      expect(a).not.toBe('')
      expect(t).not.toBe('')
      expect(s).not.toBe('')
      expect(a).not.toBe(t)
      expect(t).not.toBe(s)
      expect(a).not.toBe(s)
    })
  })
})

describe('ActorNetworkGraph — empty state (plan L6)', () => {
  it('renders the text-only "Planned · no data yet" block when nodes.length === 0', async () => {
    mockHookSuccess(EMPTY_DATA)
    const { Wrapper } = makeWrapper()
    render(<ActorNetworkGraph />, { wrapper: Wrapper })

    await waitFor(() => {
      // Reuses the same testid the L6 reserved-slot block currently
      // uses in DashboardPage.tsx so workspace-level visual
      // assertions don't fork.
      expect(
        screen.getByTestId('actor-network-graph-empty-state'),
      ).toBeInTheDocument()
    })
  })

  it('renders NO <svg> / <canvas> / synthetic marks when nodes.length === 0', async () => {
    mockHookSuccess(EMPTY_DATA)
    const { Wrapper } = makeWrapper()
    const { container } = render(<ActorNetworkGraph />, { wrapper: Wrapper })

    await waitFor(() => {
      // Hard L6 lock: the slot rendered nothing visually
      // synthetic. A future fix that fakes empty-state with a
      // sparkline / skeleton / mock SVG would fail this assertion.
      expect(container.querySelector('svg')).toBeNull()
      expect(container.querySelector('canvas')).toBeNull()
      expect(container.querySelector('circle')).toBeNull()
      expect(container.querySelector('line')).toBeNull()
      // Catch the generic synthetic-marks vocabulary too. Codex r5
      // M4 fold: plan T4 lists `node|edge|chart-marks` as the full
      // negative vocabulary; pin all three families.
      expect(
        container.querySelector(
          '[data-testid*="chart-marks"],' +
          '[data-testid*="sparkline"],' +
          '[data-testid*="skeleton"]',
        ),
        'empty state must not render chart-marks/sparkline/skeleton',
      ).toBeNull()
      // The slot's outer container ALSO uses `actor-network-node-`
      // and `actor-network-edge-` testid prefixes for populated
      // shapes, but the empty-state path must NOT emit those.
      // Permit the empty-state's own shell testid (which has
      // 'empty-state' in the name) but block any 'node-' / 'edge-'
      // child marker.
      expect(
        container.querySelector(
          '[data-testid^="actor-network-node-"],' +
          '[data-testid^="actor-network-edge-"]',
        ),
        'empty state must not render node-/edge- testid children',
      ).toBeNull()
    })
  })
})

describe('ActorNetworkGraph — topology-change reseed (plan L13)', () => {
  it('different topology with equal cardinality re-runs the d3-force useEffect', async () => {
    // First render: POPULATED_DATA
    mockHookSuccess(POPULATED_DATA)
    const { Wrapper } = makeWrapper()
    const { container, rerender } = render(<ActorNetworkGraph />, {
      wrapper: Wrapper,
    })
    await waitFor(() => {
      expect(container.querySelectorAll('circle')).toHaveLength(
        POPULATED_DATA.nodes.length,
      )
    })

    // Capture positions of node 0 BEFORE the topology flip.
    const firstCircleBefore = container.querySelector('circle') as SVGCircleElement
    const cxBefore = parseFloat(firstCircleBefore.getAttribute('cx') ?? '0')
    const cyBefore = parseFloat(firstCircleBefore.getAttribute('cy') ?? '0')

    // Re-render with DIFFERENT topology, same cardinality.
    mockHookSuccess(POPULATED_DATA_DIFFERENT_TOPOLOGY)
    rerender(<ActorNetworkGraph />)
    await waitFor(() => {
      // After the topology flip, the layout MUST reseed — at
      // minimum, the node count is preserved and the testids
      // reflect the new ids.
      expect(
        screen.getByTestId('actor-network-node-actor:9'),
      ).toBeInTheDocument()
    })

    // Positions reseed: at least one of (cx, cy) of the first node
    // must differ from before. If the useEffect didn't re-run, d3-
    // force would not re-position even though nodes have new ids.
    const firstCircleAfter = container.querySelector('circle') as SVGCircleElement
    const cxAfter = parseFloat(firstCircleAfter.getAttribute('cx') ?? '0')
    const cyAfter = parseFloat(firstCircleAfter.getAttribute('cy') ?? '0')
    expect(cxBefore !== cxAfter || cyBefore !== cyAfter).toBe(true)
  })
})

describe('ActorNetworkGraph — cap-breach signaling (plan §5 row #7)', () => {
  it('renders an explanatory testid when cap_breached: true', async () => {
    mockHookSuccess({
      ...POPULATED_DATA,
      cap_breached: true,
    })
    const { Wrapper } = makeWrapper()
    render(<ActorNetworkGraph />, { wrapper: Wrapper })

    await waitFor(() => {
      // Surface for the analyst-facing explanation. Exact copy
      // owned by i18n; this test pins only that the surface
      // exists when the flag is set.
      expect(
        screen.getByTestId('actor-network-graph-cap-breached'),
      ).toBeInTheDocument()
    })
  })

  it('does NOT render the cap-breach surface when cap_breached: false', async () => {
    mockHookSuccess({
      ...POPULATED_DATA,
      cap_breached: false,
    })
    const { Wrapper } = makeWrapper()
    render(<ActorNetworkGraph />, { wrapper: Wrapper })

    await waitFor(() => {
      expect(
        screen.getByTestId('actor-network-node-actor:1'),
      ).toBeInTheDocument()
    })
    expect(
      screen.queryByTestId('actor-network-graph-cap-breached'),
    ).toBeNull()
  })
})

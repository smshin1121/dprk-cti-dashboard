/**
 * Actor-network co-occurrence graph (PR 3 T10).
 *
 * Plan ``docs/plans/actor-network-data.md`` v1.6 L2 + L4 + L6 + L13
 * (and §0.1 amendment for the L12 `useEffect` → `useMemo` deviation —
 * Codex r9 M1 fold required `useMemo` so that label/kind/degree on
 * same-topology refetch render fresh from CURRENT props, not stale
 * from a memoized full-node payload).
 *
 * Layout: d3-force run synchronously (`tick(300)` then `.stop()`)
 * inside `useMemo` keyed on the L13 stable topology signature
 * (`JSON.stringify` of sorted node ids + sorted
 * `source_id:target_id:weight` triples — literal-locked by plan
 * L13). Result: topology-equal renders share the same memoized
 * layout; different topologies recompute. No continuous animation
 * in v1.
 *
 * Empty-state branch preserves the L6 reserved-slot vocabulary —
 * same outer testids (`actor-network-graph-slot`,
 * `actor-network-graph-title`, `actor-network-graph-empty-state`),
 * same `Planned · no data yet` copy. NO svg / canvas / synthetic
 * marks when `nodes.length === 0` — pinned by T4 negative
 * assertion.
 *
 * Cap-breach surface (`actor-network-graph-cap-breached`) renders
 * inline with the SVG when the BE flags `cap_breached: true`
 * (selected actors guaranteed inclusion; default cap exceeded —
 * plan §5 row #7 + L7).
 *
 * Subscription discipline: imports `useActorNetwork`, NOT the
 * dashboard-summary shared-cache hook. Pinned by T5 architectural
 * guard.
 */

import {
  forceCenter,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import type {
  ActorNetworkEdge,
  ActorNetworkNode,
} from '../../lib/api/schemas'
import { useActorNetwork } from '../analytics/useActorNetwork'

const SVG_WIDTH = 600
const SVG_HEIGHT = 360
const MIN_RADIUS = 4
const MAX_RADIUS = 16

// Stroke values resolve to DESIGN.md tokens via the
// `apps/frontend/src/styles/tokens.css` HSL CSS variable layer
// (`--muted-soft`, `--status-warning|info|success`). SVG `stroke`
// accepts `hsl(...)` directly, so the T4 distinct-stroke assertion
// can still read `getAttribute('stroke')` and compare distinctness;
// the exact RGB value is owned by the token layer.
const EDGE_STROKE = 'hsl(var(--muted-soft))'

// Distinct stroke per kind (DESIGN.md categorical → Ferrari status
// palette mapping per `tokens.css` §"Status palette"):
//   actor  → status-warning  (#f13a2c — warning red, was #ef4444)
//   tool   → status-info     (#4c98b9 — info blue,    was #3b82f6)
//   sector → status-success  (#03904a — success green, was #10b981)
const KIND_STROKE: Record<ActorNetworkNode['kind'], string> = {
  actor: 'hsl(var(--status-warning))',
  tool: 'hsl(var(--status-info))',
  sector: 'hsl(var(--status-success))',
}

// Concrete simulation-node shape: d3-force's SimulationNodeDatum
// declares `x`/`y` as optional, but our `layoutPositions` writes
// concrete numbers at init. Extending it keeps `id` typed and lets
// the generics on forceSimulation / forceLink replace the prior
// `as never` + `as unknown as { id: string }` casts (Codex r9 L3).
interface SimNode extends SimulationNodeDatum {
  id: string
}

function topologySignature(
  nodes: readonly ActorNetworkNode[],
  edges: readonly ActorNetworkEdge[],
): string {
  // Canonical signature literal-locked by plan v1.6 L13: sorted node
  // ids + sorted `source_id:target_id:weight` triples wrapped in
  // JSON.stringify. Sorts make the signature insensitive to BE return
  // order; including weight makes it sensitive to weight changes that
  // affect simulation forces.
  return JSON.stringify({
    n: [...nodes].map((x) => x.id).sort(),
    e: [...edges]
      .map((e) => `${e.source_id}:${e.target_id}:${e.weight}`)
      .sort(),
  })
}

function radiusForDegree(degree: number, maxDegree: number): number {
  if (maxDegree <= 0) return MIN_RADIUS
  const t = Math.min(1, Math.max(0, degree / maxDegree))
  return MIN_RADIUS + t * (MAX_RADIUS - MIN_RADIUS)
}

// Hash a node id to a stable seed in [-1, 1) so each node's initial
// position depends on its identity, not on array index. With identical
// node counts but different ids the simulation starts from different
// initial conditions — propagated by force-link/charge perturbation,
// the post-tick layout WILL differ (pins T4 topology-change reseed).
// `Math.abs` normalizes the negative-modulo case so the spread is
// genuinely centred (Codex r9 L2 fold).
function hashId(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i += 1) {
    h = (h * 31 + id.charCodeAt(i)) | 0
  }
  return ((Math.abs(h) % 2000) - 1000) / 1000
}

function layoutPositions(
  nodes: readonly ActorNetworkNode[],
  edges: readonly ActorNetworkEdge[],
): Map<string, { x: number; y: number }> {
  // d3-force mutates simulation nodes in place. Spread into mutable
  // local objects so the props array is untouched. We pass ONLY id +
  // x + y to the simulation; label/kind/degree don't influence the
  // layout, and keeping them out of the memo prevents Codex r9 M1's
  // stale-render hazard (a refetch with identical topology but
  // changed label/kind/degree must STILL render fresh values).
  const simNodes: SimNode[] = nodes.map((n) => ({
    id: n.id,
    x: SVG_WIDTH / 2 + hashId(n.id) * 120,
    y: SVG_HEIGHT / 2 + hashId(`${n.id}:y`) * 80,
  }))
  const simEdges: SimulationLinkDatum<SimNode>[] = edges.map((e) => ({
    source: e.source_id,
    target: e.target_id,
  }))

  // Generics on forceSimulation + forceLink thread the concrete
  // `SimNode` shape through, so `.id((d) => d.id)` resolves without
  // the prior `as unknown as { id: string }` cast. The simulation
  // mutates `x`/`y` in place after each tick.
  const simulation = forceSimulation<SimNode>(simNodes)
    .force(
      'link',
      forceLink<SimNode, SimulationLinkDatum<SimNode>>(simEdges)
        .id((d) => d.id)
        .distance(80),
    )
    .force('charge', forceManyBody<SimNode>().strength(-150))
    .force('center', forceCenter(SVG_WIDTH / 2, SVG_HEIGHT / 2))
    .stop()

  simulation.tick(300)

  const map = new Map<string, { x: number; y: number }>()
  for (const n of simNodes) {
    map.set(n.id, {
      x: typeof n.x === 'number' ? n.x : SVG_WIDTH / 2,
      y: typeof n.y === 'number' ? n.y : SVG_HEIGHT / 2,
    })
  }
  return map
}

export function ActorNetworkGraph(): JSX.Element {
  const { t } = useTranslation()
  const { data } = useActorNetwork()

  const nodes = data?.nodes ?? []
  const edges = data?.edges ?? []
  const capBreached = data?.cap_breached ?? false

  const signature = topologySignature(nodes, edges)

  // Memoize POSITIONS only, keyed on topology. label / kind / degree
  // are NOT part of the memo so a refetch that changes those (with
  // same topology) re-renders fresh values without recomputing the
  // expensive d3-force layout. Codex r9 M1 fold.
  const positionMap = useMemo(
    () =>
      nodes.length > 0
        ? layoutPositions(nodes, edges)
        : new Map<string, { x: number; y: number }>(),
    // The signature captures the topology dependency; nodes/edges are
    // read inside the closure for current data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signature],
  )

  const maxDegree = nodes.reduce((acc, n) => Math.max(acc, n.degree), 0)

  return (
    <section
      data-testid="actor-network-graph-slot"
      aria-labelledby="actor-network-graph-heading"
      className="rounded-none border border-border-card bg-surface p-4"
    >
      <h3
        id="actor-network-graph-heading"
        data-testid="actor-network-graph-title"
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t('dashboard.actorNetwork.title')}
      </h3>

      {nodes.length === 0 ? (
        <p
          data-testid="actor-network-graph-empty-state"
          className="text-sm text-ink-muted"
        >
          {t('dashboard.actorNetwork.plannedEmptyState')}
        </p>
      ) : (
        <>
          {capBreached ? (
            <p
              data-testid="actor-network-graph-cap-breached"
              className="mb-2 text-xs text-ink-muted"
            >
              {t('dashboard.actorNetwork.capBreachedNotice')}
            </p>
          ) : null}
          <svg
            viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
            className="h-auto w-full"
            role="img"
            aria-label={t('dashboard.actorNetwork.title')}
          >
            {edges.map((e) => {
              const src = positionMap.get(e.source_id)
              const tgt = positionMap.get(e.target_id)
              if (!src || !tgt) return null
              return (
                <line
                  key={`${e.source_id}|${e.target_id}|${e.weight}`}
                  x1={src.x}
                  y1={src.y}
                  x2={tgt.x}
                  y2={tgt.y}
                  stroke={EDGE_STROKE}
                  strokeWidth={Math.max(1, Math.log1p(e.weight))}
                />
              )
            })}
            {nodes.map((n) => {
              // Render from CURRENT nodes (not the topology-memoized
              // layout), joined to the position map. A refetch with
              // same topology + new label / kind / degree updates
              // here without re-running the d3 simulation.
              const pos =
                positionMap.get(n.id) ?? {
                  x: SVG_WIDTH / 2,
                  y: SVG_HEIGHT / 2,
                }
              return (
                <g
                  key={n.id}
                  data-testid={`actor-network-node-${n.id}`}
                  aria-label={`${n.kind}: ${n.label} (degree ${n.degree})`}
                >
                  <circle
                    cx={pos.x}
                    cy={pos.y}
                    r={radiusForDegree(n.degree, maxDegree)}
                    stroke={KIND_STROKE[n.kind]}
                    strokeWidth={2}
                    fill="white"
                  />
                </g>
              )
            })}
          </svg>
        </>
      )}
    </section>
  )
}

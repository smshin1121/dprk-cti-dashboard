/**
 * Actor-network co-occurrence graph (PR 3 T10).
 *
 * Plan ``docs/plans/actor-network-data.md`` v1.6 L2 + L4 + L6 + L13.
 *
 * Layout: d3-force run synchronously (`tick(300)` then `.stop()`)
 * inside `useMemo` keyed on the L13 stable topology signature
 * (sorted node ids + sorted `source:target:weight` triples). Result:
 * topology-equal renders share the same memoized layout; different
 * topologies recompute. No continuous animation in v1.
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
const EDGE_STROKE = '#94a3b8'

// Distinct stroke per kind (DESIGN.md actor-network vocabulary). The
// stroke ATTRIBUTE — not a class — so the T4 distinct-stroke
// assertion can read `getAttribute('stroke')` directly.
const KIND_STROKE: Record<ActorNetworkNode['kind'], string> = {
  actor: '#ef4444',
  tool: '#3b82f6',
  sector: '#10b981',
}

interface PositionedNode extends ActorNetworkNode {
  x: number
  y: number
}

function topologySignature(
  nodes: readonly ActorNetworkNode[],
  edges: readonly ActorNetworkEdge[],
): string {
  const sortedNodeIds = nodes.map((n) => n.id).slice().sort().join(',')
  const sortedEdges = edges
    .map((e) => `${e.source_id}:${e.target_id}:${e.weight}`)
    .slice()
    .sort()
    .join(',')
  return `${sortedNodeIds}||${sortedEdges}`
}

function radiusForDegree(degree: number, maxDegree: number): number {
  if (maxDegree <= 0) return MIN_RADIUS
  const t = Math.min(1, Math.max(0, degree / maxDegree))
  return MIN_RADIUS + t * (MAX_RADIUS - MIN_RADIUS)
}

// Hash a node id to a stable seed in [-1, 1] so each node's initial
// position depends on its identity, not on array index. With identical
// node counts but different ids the simulation starts from different
// initial conditions — propagated by force-link/charge perturbation,
// the post-tick layout WILL differ (pins T4 topology-change reseed).
function hashId(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i += 1) {
    h = (h * 31 + id.charCodeAt(i)) | 0
  }
  // Map to [-1, 1] range based on the lower bits (stable across runs).
  return ((h % 2000) - 1000) / 1000
}

function layoutNetwork(
  nodes: readonly ActorNetworkNode[],
  edges: readonly ActorNetworkEdge[],
): PositionedNode[] {
  // d3-force mutates simulation nodes in place. Spread into mutable
  // local objects to avoid mutating the props array.
  const simNodes = nodes.map((n) => ({
    ...n,
    x: SVG_WIDTH / 2 + hashId(n.id) * 120,
    y: SVG_HEIGHT / 2 + hashId(`${n.id}:y`) * 80,
  }))
  const simEdges = edges.map((e) => ({
    source: e.source_id,
    target: e.target_id,
  }))

  // d3-force types declare a permissive `SimulationNodeDatum` for
  // `forceLink.id`; cast through `unknown` to thread our concrete
  // node shape (`{id: string, x, y}`). The simulation mutates `x`/`y`
  // in place after each tick.
  const simulation = forceSimulation(simNodes as never)
    .force(
      'link',
      forceLink(simEdges as never)
        .id((d) => (d as unknown as { id: string }).id)
        .distance(80),
    )
    .force('charge', forceManyBody().strength(-150))
    .force('center', forceCenter(SVG_WIDTH / 2, SVG_HEIGHT / 2))
    .stop()

  simulation.tick(300)

  return simNodes.map((n) => ({
    ...(n as ActorNetworkNode),
    x: typeof n.x === 'number' ? n.x : SVG_WIDTH / 2,
    y: typeof n.y === 'number' ? n.y : SVG_HEIGHT / 2,
  }))
}

export function ActorNetworkGraph(): JSX.Element {
  const { t } = useTranslation()
  const { data } = useActorNetwork()

  const nodes = data?.nodes ?? []
  const edges = data?.edges ?? []
  const capBreached = data?.cap_breached ?? false

  const signature = topologySignature(nodes, edges)

  const positionedNodes = useMemo(
    () => (nodes.length > 0 ? layoutNetwork(nodes, edges) : []),
    // Layout depends only on the topology signature — identical
    // signatures share the memoized layout; different signatures
    // recompute. Nodes/edges are read inside the closure but the
    // signature captures both.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signature],
  )

  const positionMap = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>()
    for (const n of positionedNodes) map.set(n.id, { x: n.x, y: n.y })
    return map
  }, [positionedNodes])

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
            {positionedNodes.map((n) => (
              <g
                key={n.id}
                data-testid={`actor-network-node-${n.id}`}
                aria-label={`${n.kind}: ${n.label} (degree ${n.degree})`}
              >
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={radiusForDegree(n.degree, maxDegree)}
                  stroke={KIND_STROKE[n.kind]}
                  strokeWidth={2}
                  fill="white"
                />
              </g>
            ))}
          </svg>
        </>
      )}
    </section>
  )
}

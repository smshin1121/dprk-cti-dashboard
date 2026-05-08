/**
 * ActorNetworkGraph.tsx architectural guard — static-source assertion
 * (PR 3 T5).
 *
 * Plan ``docs/plans/actor-network-data.md`` v1.6 §4 T5 + L1 + memory
 * `pattern_shared_cache_test_extension`:
 *
 *   `ActorNetworkGraph.tsx` MUST NOT import `useDashboardSummary`.
 *   The dashboard's KPI / GroupsMiniList / SectorBreakdown / etc. all
 *   share `summarySharedCache`; adding actor-network as a 7th
 *   subscriber would break the shared-cache invariant pinned by
 *   `summarySharedCache.test.tsx`. The actor-network slot has its
 *   own isolated cache (`useActorNetwork`, plan §7 AC #6).
 *
 * Mirrors `apps/frontend/src/layout/__tests__/Shell.architectural-guard.test.tsx`
 * — readFileSync + grep-style negative imports.
 *
 * RED note: this test is GREEN at branch-creation time once the
 * placeholder file exists (it doesn't import `useDashboardSummary`).
 * The test exists to STAY green forever — i.e., it's a regression
 * guard, not a TDD-RED pin. Listed under T5 in the plan because the
 * contract pin happens here.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const ACTOR_NETWORK_GRAPH_PATH = resolve(
  __dirname,
  '..',
  'ActorNetworkGraph.tsx',
)

describe('ActorNetworkGraph architectural guard', () => {
  it('ActorNetworkGraph.tsx exists and is readable', () => {
    expect(() => readFileSync(ACTOR_NETWORK_GRAPH_PATH, 'utf-8')).not.toThrow()
  })

  it('does NOT import useDashboardSummary (cache-isolation contract)', () => {
    const source = readFileSync(ACTOR_NETWORK_GRAPH_PATH, 'utf-8')
    // Match any import / re-export from a path containing
    // `useDashboardSummary`. Both forward-slash and backward-slash
    // path separators on Windows are covered.
    const dashboardSummaryImport =
      /from\s+['"][^'"]*useDashboardSummary/g
    const matches = source.match(dashboardSummaryImport)
    expect(
      matches,
      `ActorNetworkGraph.tsx must not import useDashboardSummary. Found: ${
        matches ? matches.join(', ') : 'none'
      }`,
    ).toBeNull()
  })

  it('does NOT reference the useDashboardSummary symbol (negative pin)', () => {
    const source = readFileSync(ACTOR_NETWORK_GRAPH_PATH, 'utf-8')
    // Symbol-level negative — even a re-export that smuggles the
    // shared-cache hook in via another module would fail this.
    expect(source).not.toMatch(/\buseDashboardSummary\b/)
  })

  it('does NOT subscribe to summarySharedCache directly', () => {
    const source = readFileSync(ACTOR_NETWORK_GRAPH_PATH, 'utf-8')
    // Same lock at the cache key layer — adding actor-network to
    // the shared cache slot would break the 6-subscriber invariant
    // pinned by `summarySharedCache.test.tsx`.
    expect(source).not.toMatch(/\bsummarySharedCache\b/)
  })
})

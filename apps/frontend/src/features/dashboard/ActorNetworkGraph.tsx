/**
 * Actor-network co-occurrence graph component (PR 3 T10 placeholder).
 *
 * Plan ``docs/plans/actor-network-data.md`` v1.6 L2 + L4 + L13:
 *   d3-force layout, stopped-and-ticked (`tick(300)` + `.stop()`), SVG
 *   render, kind-prefixed node ids (`actor:` / `tool:` / `sector:`),
 *   stable topology signature for the layout `useEffect` key.
 *
 * **PLACEHOLDER** for T3-T5 RED batch. T10 GREEN replaces this with
 * the real component — `ActorNetworkGraph.test.tsx` tests will flip
 * RED → GREEN at that point. The placeholder satisfies vitest
 * collection (`pattern_tdd_stub_for_red_collection`) and lets the
 * architectural-guard test (T5) act as a regression guard from day
 * one — it does NOT import the dashboard-summary shared-cache hook
 * (per plan L1 + memory `pattern_shared_cache_test_extension`). The
 * specific symbol name is asserted-against in the architectural
 * guard, so this comment intentionally avoids spelling it.
 */

export interface ActorNetworkGraphProps {
  // T10 GREEN populates this. Empty for the placeholder.
}

export function ActorNetworkGraph(_props: ActorNetworkGraphProps = {}) {
  return null
}

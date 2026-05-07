/**
 * `/api/v1/analytics/actor_network` React Query hook (PR 3 T9 stub).
 *
 * Plan ``docs/plans/actor-network-data.md`` v1.6 L2 + L5 + T9:
 *   primitive `useFilterStore` selectors for `dateFrom` / `dateTo` /
 *   `groupIds`; per-instance `top_n_actor` / `top_n_tool` /
 *   `top_n_sector` options; `staleTime: 30_000` mirroring sibling
 *   analytics hooks; **isolated cache slot** — does NOT subscribe to
 *   `summarySharedCache` (per plan §7 AC #6 + memory
 *   `pattern_shared_cache_test_extension`).
 *
 * **STUB** for T3 RED batch. T9 GREEN replaces this with the real
 * react-query hook — `useActorNetwork.test.tsx` tests flip RED →
 * GREEN at that point. The stub satisfies vitest collection
 * (`pattern_tdd_stub_for_red_collection`):
 *   - The queryKey deliberately uses a sentinel (`__t9-stub__`) so
 *     queryKey assertions in T3 fail with a clear "expected ...
 *     got __t9-stub__" message.
 *   - The queryFn throws so any `isSuccess` / URL / response-shape
 *     assertion fails with a clear runtime error captured in the
 *     hook's `error` field, NOT as an unhandled exception.
 */

import { useQuery } from '@tanstack/react-query'

export interface ActorNetworkOptions {
  /** Per-instance actor cap; BE bounds [1, 200] with default 25. */
  top_n_actor?: number
  /** Per-instance tool cap; BE bounds [1, 200] with default 25. */
  top_n_tool?: number
  /** Per-instance sector cap; BE bounds [1, 200] with default 25. */
  top_n_sector?: number
}

export function useActorNetwork(_options: ActorNetworkOptions = {}) {
  return useQuery({
    queryKey: ['__t9-stub__'],
    queryFn: () => {
      throw new Error(
        'useActorNetwork T9 GREEN pending — stub exists only to ' +
          'satisfy vitest collection at T3 RED time.',
      )
    },
    retry: false,
  })
}

/**
 * `/api/v1/search` React Query hook — PR #17 Phase 3 slice 3 Group D
 * (plan D8 + D9 + D13 + D17).
 *
 * Two invariants this module enforces separately:
 *
 *   1. **Debounce** (plan D17 / 250ms). Keystrokes arriving faster
 *      than 250ms collapse onto a single query. The debounced value
 *      is what flows into the React Query key AND into the request
 *      query string — so (a) identical post-debounce values share a
 *      cache slot, and (b) the BE never sees the intermediate
 *      keystrokes.
 *
 *   2. **Empty / blank guard** (plan D13 / BE 422 defense). The BE
 *      rejects empty `q` with 422; the hook MUST NOT fire a request
 *      for a blank string. The `enabled` flag is independent of the
 *      debounce window — it is computed from the debounced value's
 *      `.trim().length > 0` check so that a user typing whitespace
 *      never triggers an in-flight request.
 *
 * These two gates are separate because they answer different
 * questions: the debounce shapes WHICH value fires the query, the
 * enable guard decides WHETHER a query fires at all. Collapsing
 * them would tempt a future edit that (e.g.) bypasses the debounce
 * when the user hits Enter, at which point the enable logic also
 * silently changes. Keeping them orthogonal lets either rule evolve
 * without trapping the other.
 *
 * Subscription discipline (same pattern as `useActorReports`):
 *
 *   No FilterBar state reaches this hook — cache scope is exactly
 *   `(q, filters)` where `filters` is the `SearchFilters` whitelist
 *   `{date_from?, date_to?, limit?}`. A FilterBar TLP / group toggle
 *   MUST NOT invalidate this query; enforced by the `queryKeys.
 *   searchHits` type surface plus `queryKeys.test.ts`.
 *
 * Refetch policy: `staleTime: 30_000` — same budget as the list +
 * actor-reports hooks; analyst usage (typing, tweaking date range)
 * produces bursty fetches and a 30s stale window absorbs the
 * follow-up refocus without a double-fetch.
 */

import { useEffect, useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { getSearchHits } from '../../lib/api/endpoints'
import type { SearchResponse } from '../../lib/api/schemas'
import type { SearchFilters } from '../../lib/listFilters'
import { queryKeys } from '../../lib/queryKeys'

export const SEARCH_DEBOUNCE_MS = 250

/**
 * Debounce for the search query string. Returns a value that lags
 * `raw` by `delay` ms; importantly, **initializes to the empty
 * string on mount** rather than to `raw`. That matters because the
 * initial raw value on a palette-first-open render is ``''``, but
 * for a route that mounts with a non-empty `raw` (e.g., restored
 * state) we still want the 250ms wait — a wait long enough that a
 * human can't perceive a double-fetch, short enough that a restored
 * query still fires quickly.
 *
 * Keeping this inline (not in `lib/`) is deliberate: the hook is the
 * only consumer, the useState initializer choice above is not
 * generalizable, and a lifted version would need a three-mode API
 * (instant / delayed-first / always-delayed). When a second consumer
 * actually arrives, lifting is mechanical.
 */
function useDebouncedSearchQuery(raw: string, delay: number): string {
  const [debounced, setDebounced] = useState<string>('')
  useEffect(() => {
    const handle = setTimeout(() => setDebounced(raw), delay)
    return () => clearTimeout(handle)
  }, [raw, delay])
  return debounced
}

export function useSearchHits(q: string, filters: SearchFilters = {}) {
  const debouncedRaw = useDebouncedSearchQuery(q, SEARCH_DEBOUNCE_MS)
  // Trim AFTER debounce so the enable gate always reflects the same
  // string that went into the cache key + the BE request.
  const qTrimmed = debouncedRaw.trim()

  return useQuery<SearchResponse>({
    queryKey: queryKeys.searchHits(qTrimmed, filters),
    queryFn: ({ signal }) => getSearchHits(qTrimmed, filters, signal),
    enabled: qTrimmed.length > 0,
    staleTime: 30_000,
  })
}

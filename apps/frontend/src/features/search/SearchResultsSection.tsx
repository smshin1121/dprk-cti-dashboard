/**
 * Palette search results — PR #17 Phase 3 slice 3 Group E
 * (plan D8 + D10 + D17).
 *
 * Renders BELOW the static ⌘K command list as a sibling
 * `Command.Group`, NOT mixed into the `COMMAND_IDS.map(...)` body.
 * That separation matters for two reasons:
 *
 *   1. The static command set is plan D3 scope: navigation
 *      (/dashboard, /reports, /incidents, /actors,
 *      /analytics/correlation), filters.clear, and auth.logout.
 *      Interleaving server-backed hits into that registry would
 *      blur its contract and make a scope-lock review across PRs
 *      painful.
 *   2. cmdk's fuzzy-match filter runs per `Command.Item` and uses
 *      each item's `value`. The BE has already done the matching; we
 *      `forceMount` the hit items so the FE client-side fuzzy filter
 *      never hides a row the BE returned.
 *
 * Four render states (review criterion #1):
 *
 *   - **loading** — `q.trim().length > 0` but `useSearchHits` has
 *     not produced data yet. Covers both the 250ms debounce window
 *     (query is idle with `data === undefined`) and the in-flight
 *     fetch — merged so the visual stays continuous.
 *   - **error** — query transitioned to `isError`. Disabled row with
 *     a copy indicating the failure; retry is a user re-type (the
 *     React Query default of `retry: 3` already absorbed transients).
 *   - **empty** — D10 200 + `{items: []}`. Disabled row says "no
 *     matches for X"; never falls back to a heuristic or fake row
 *     (memory `pattern_d10_empty_as_first_class_state`).
 *   - **populated** — one `Command.Item` per hit. Selection fires
 *     `onSelectResult(report.id)` which the palette owner uses to
 *     navigate + close.
 *
 * If `q.trim()` is empty the section renders nothing at all — the
 * user sees only the 7 static commands, exactly as before PR #17.
 */

import { Command } from 'cmdk'

import { useSearchHits } from './useSearchHits'

export interface SearchResultsSectionProps {
  /** Raw palette input — untrimmed, undebounced. The hook owns both. */
  q: string
  /** Palette owner callback — navigates + closes on selection. */
  onSelectResult: (reportId: number) => void
}

export function SearchResultsSection({
  q,
  onSelectResult,
}: SearchResultsSectionProps): JSX.Element | null {
  const query = useSearchHits(q)
  const trimmed = q.trim()

  // No-q branch — render nothing. Static command list stands alone.
  if (trimmed.length === 0) return null

  // Error branch — surface above empty so a transient fetch failure
  // is not silently painted as "no matches".
  if (query.isError) {
    return (
      <Command.Group
        forceMount
        heading="Search results"
        data-testid="search-results-section"
      >
        <Command.Item
          data-testid="search-state-error"
          value="__search_state_error"
          forceMount
          disabled
          className="px-4 py-2 text-sm text-ink-muted"
        >
          Could not load results. Try again.
        </Command.Item>
      </Command.Group>
    )
  }

  // Loading branch — covers debounce window + in-flight fetch.
  // Merged so the palette does not flicker between "empty space" and
  // "loading row" across the two sub-phases.
  if (query.data === undefined) {
    return (
      <Command.Group
        forceMount
        heading="Search results"
        data-testid="search-results-section"
      >
        <Command.Item
          data-testid="search-state-loading"
          value="__search_state_loading"
          forceMount
          disabled
          className="px-4 py-2 text-sm text-ink-muted"
        >
          Searching…
        </Command.Item>
      </Command.Group>
    )
  }

  // Empty branch — D10 contract. 200 + items === [].
  if (query.data.items.length === 0) {
    return (
      <Command.Group
        forceMount
        heading="Search results"
        data-testid="search-results-section"
      >
        <Command.Item
          data-testid="search-state-empty"
          value="__search_state_empty"
          forceMount
          disabled
          className="px-4 py-2 text-sm text-ink-muted"
        >
          No matches for "{trimmed}"
        </Command.Item>
      </Command.Group>
    )
  }

  // Populated branch — one selectable row per hit.
  return (
    <Command.Group
      forceMount
      heading="Search results"
      data-testid="search-results-section"
    >
      <div data-testid="search-state-populated" style={{ display: 'contents' }}>
        {query.data.items.map((hit) => (
          <Command.Item
            key={hit.report.id}
            // Include the id + title in the cmdk value so any
            // residual client-side matching still finds the row —
            // but `forceMount` above keeps it visible regardless.
            value={`search-hit-${hit.report.id} ${hit.report.title}`}
            forceMount
            onSelect={() => onSelectResult(hit.report.id)}
            data-testid={`search-result-${hit.report.id}`}
            className="flex cursor-pointer flex-col gap-0.5 rounded px-4 py-2 text-sm data-[selected=true]:bg-app"
          >
            <span className="truncate">{hit.report.title}</span>
            {hit.report.published != null && (
              <span className="text-[10px] uppercase tracking-wider text-ink-subtle">
                {hit.report.published}
              </span>
            )}
          </Command.Item>
        ))}
      </div>
    </Command.Group>
  )
}

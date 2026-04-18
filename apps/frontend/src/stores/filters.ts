/**
 * Top-nav filter UI state — zustand.
 *
 * SCOPE RULE (plan D5 + D10 lock):
 * --------------------------------
 * This store owns three filter dimensions the UI lets the user adjust:
 *   - `dateFrom` / `dateTo` — ISO date strings (yyyy-mm-dd) sent to BE
 *   - `groupIds` — sent to BE as repeatable `group_id` query param
 *   - `tlpLevels` — UI-ONLY. Never serialized to a BE request.
 *
 * The TLP UI-only constraint is locked in PR #12 plan D5 because PR
 * #11 D4 deferred TLP RLS on the BE. Until the BE has TLP filtering,
 * sending tlp params would be silently dropped (best case) or
 * misinterpreted as a different filter (worst case). Either way the
 * FE would lie to the analyst about what's actually filtered.
 *
 * The store can hold TLP state — that's the UI affordance the analyst
 * sees and toggles. The contract is that the store→payload transform
 * (`lib/dashboardFilters.ts`) drops it. The transform is type-safe
 * (DashboardSummaryFilters has no tlp field) AND covered by tests
 * that assert TLP-equivalence of the emitted payload.
 *
 * D10 source-of-truth split:
 * The KPI / list data this store FILTERS lives in the React Query
 * cache, never in zustand. The filter values themselves are UI state —
 * the user's choice of what to look at — so they belong here.
 */

import { create } from 'zustand'

export const TLP_LEVELS = ['WHITE', 'GREEN', 'AMBER'] as const
export type TlpLevel = (typeof TLP_LEVELS)[number]

export interface FilterState {
  /** ISO yyyy-mm-dd, inclusive lower bound. `null` = no lower bound. */
  dateFrom: string | null
  /** ISO yyyy-mm-dd, inclusive upper bound. `null` = no upper bound. */
  dateTo: string | null
  /** Selected group ids. Empty = no group filter applied. */
  groupIds: number[]
  /** Selected TLP levels. UI-only; see module docstring. */
  tlpLevels: TlpLevel[]

  setDateRange: (from: string | null, to: string | null) => void
  toggleGroupId: (id: number) => void
  toggleTlpLevel: (level: TlpLevel) => void
  clear: () => void
}

const EMPTY: Pick<
  FilterState,
  'dateFrom' | 'dateTo' | 'groupIds' | 'tlpLevels'
> = {
  dateFrom: null,
  dateTo: null,
  groupIds: [],
  tlpLevels: [],
}

function toggle<T>(current: readonly T[], value: T): T[] {
  return current.includes(value)
    ? current.filter((v) => v !== value)
    : [...current, value]
}

export const useFilterStore = create<FilterState>((set) => ({
  ...EMPTY,
  setDateRange: (from, to) => set({ dateFrom: from, dateTo: to }),
  toggleGroupId: (id) =>
    set((s) => ({ groupIds: toggle(s.groupIds, id) })),
  toggleTlpLevel: (level) =>
    set((s) => ({ tlpLevels: toggle(s.tlpLevels, level) })),
  clear: () => set(EMPTY),
}))

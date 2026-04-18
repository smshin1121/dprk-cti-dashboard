/**
 * Dashboard view + tab selection — zustand. Plan D4 lock (PR #13).
 *
 * Scope:
 * This store holds the "which sub-panel is the analyst focused on"
 * state that the /dashboard route exposes via URL (?view=...&tab=...).
 * Concrete values (valid view ids, tab ids per view) are defined by
 * the viz groups G/H/I when they land — Group E only wires the state
 * pipe + URL sync so the downstream groups plug in without a schema
 * revision.
 *
 * `view` and `tab` are intentionally typed as opaque `string | null`:
 *
 * - `null` means "no view / tab selected" (default dashboard rendering)
 * - Concrete values are produced/consumed by future dashboard
 *   components (Group I's AttackHeatmap might set view="attack",
 *   Group G's WorldMap might set view="geo", etc.)
 * - The URL-state layer treats them as opaque; there is no runtime
 *   allowlist here because any allowlist would force this file to
 *   change every time a new viz component lands.
 *
 * D10 compliance:
 * Like filters + theme, view/tab are UI state — a user's focus choice.
 * No server endpoint knows about them. zustand is the right home,
 * NOT React Query.
 *
 * URL-sync contract:
 * `useFilterUrlSync` reads these with primitive selectors and writes
 * to the URL via `history.replaceState`. When `pathname !== /dashboard`
 * the hook suppresses the view/tab URL entries — scoping them to
 * their owning route. The store itself is global (one user, one
 * current dashboard state) but the URL representation is route-
 * scoped.
 */

import { create } from 'zustand'

export interface DashboardViewState {
  /** Currently focused dashboard sub-view (e.g. "attack", "geo").
   *  `null` = default rendering, no focused sub-panel. */
  view: string | null
  /** Tab within the active view (e.g. "overview", "details").
   *  `null` = default tab, interpretation is view-dependent. */
  tab: string | null

  setView: (view: string | null) => void
  setTab: (tab: string | null) => void
  /** Reset both — convenience for "back to default dashboard". */
  clear: () => void
}

const EMPTY: Pick<DashboardViewState, 'view' | 'tab'> = {
  view: null,
  tab: null,
}

export const useDashboardViewStore = create<DashboardViewState>((set) => ({
  ...EMPTY,
  setView: (view) => set({ view }),
  setTab: (tab) => set({ tab }),
  clear: () => set(EMPTY),
}))

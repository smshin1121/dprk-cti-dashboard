/**
 * URL ⇄ store sync — plan D4. Runs once at the Shell level so every
 * authenticated route participates.
 *
 * Contract:
 *
 * 1. **Hydrate on mount** — one-shot `useEffect` reads the current
 *    URL via `window.location.search`, decodes through `decodeUrlState`,
 *    and writes filters + (if on /dashboard) view/tab into their
 *    zustand stores. The decoder canonicalizes groupIds ascending so
 *    the initial URL's order does not matter.
 *
 * 2. **Emit on store change** — a subscribe effect with primitive
 *    selectors (dateFrom / dateTo / groupIds / view / tab — NEVER
 *    tlpLevels) encodes the current state, compares to the live URL
 *    search string, and writes via `history.replaceState` only when
 *    they differ. Identity short-circuit blocks the "store → URL →
 *    (no op) → store" ping-pong that would otherwise fire after mount
 *    hydration wrote the store.
 *
 * 3. **Back / forward (popstate)** — a `popstate` listener re-decodes
 *    the URL and writes back into the stores. The subsequent emit
 *    effect sees matching state → URL and short-circuits (no
 *    replaceState), so the browser's back entry stays intact.
 *
 * 4. **Route scoping of view/tab** — `view` + `tab` only flow to the
 *    URL when `location.pathname === '/dashboard'`. Navigating off
 *    the dashboard drops those params from the URL without touching
 *    the store values (a subsequent return to /dashboard rehydrates
 *    them). Non-dashboard URLs carry only filter params.
 *
 * 5. **Page-local URL state — emit short-circuit** (PR-B T10 r1
 *    fold). `/analytics/correlation` (PR-B Phase 3 Slice 3 D-1)
 *    owns its OWN URL surface (`x` / `y` / `date_from` / `date_to`
 *    / `method`) inside `CorrelationPage`. The encoder above only
 *    knows about the global keys, so emitting from this hook on
 *    correlation routes would replace the entire search string and
 *    strip those page-local params. We short-circuit emit on the
 *    correlation pathname; `CorrelationPage`'s own
 *    `replaceState` write keeps its surface in sync. Hydrate stays
 *    enabled — the correlation URL has no global keys, so the
 *    decoder cleanly resolves to `dateFrom: null, dateTo: null,
 *    groupIds: []`, which is correct for that route's defaults.
 *
 * Contracts NOT participating in this sync:
 *   - `tlpLevels` — plan D4 + carried D5 lock (UI-only).
 *   - Pagination cursors, dialog-open flags, hover state, ⌘K open.
 *   - Auth / session — cookie-scoped.
 *
 * The sync is intentionally co-located in a single hook so the
 * "how does URL stay in sync" answer lives in one file. A future move
 * (e.g., to a route-scoped mount instead of Shell) is a one-import
 * change.
 */

import { useEffect, useLayoutEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'

import {
  decodeUrlState,
  encodeUrlState,
  urlStateSearchString,
  type UrlState,
} from '../../lib/urlState'
import { useDashboardViewStore } from '../../stores/dashboardView'
import { useFilterStore } from '../../stores/filters'

const DASHBOARD_PATH = '/dashboard'
const CORRELATION_PATH = '/analytics/correlation'

function readUrlSearch(): string {
  if (typeof window === 'undefined') return ''
  // `.search` includes the leading '?'; strip it for comparisons
  // against URLSearchParams.toString() which does NOT include '?'.
  return window.location.search.startsWith('?')
    ? window.location.search.slice(1)
    : window.location.search
}

function writeUrlSearch(search: string): void {
  if (typeof window === 'undefined') return
  const pathname = window.location.pathname
  const hash = window.location.hash
  const next = `${pathname}${search ? `?${search}` : ''}${hash}`
  // `replaceState` does NOT fire popstate — intentional: the sync
  // must not re-hydrate the store and restart the cycle.
  window.history.replaceState(window.history.state, '', next)
}

function hydrateStoresFromUrl(includeView: boolean): void {
  const params = new URLSearchParams(readUrlSearch())
  const decoded = decodeUrlState(params)

  // Filter store — always hydrated. Preserves `tlpLevels` as-is; the
  // URL has no opinion on TLP (plan D4 lock).
  useFilterStore.setState({
    dateFrom: decoded.dateFrom,
    dateTo: decoded.dateTo,
    groupIds: decoded.groupIds,
  })

  if (includeView) {
    useDashboardViewStore.setState({
      view: decoded.view,
      tab: decoded.tab,
    })
  }
}

export function useFilterUrlSync(): void {
  const location = useLocation()
  const pathname = location.pathname
  const isDashboard = pathname === DASHBOARD_PATH
  const isPageLocalUrlState = pathname === CORRELATION_PATH

  const dateFrom = useFilterStore((s) => s.dateFrom)
  const dateTo = useFilterStore((s) => s.dateTo)
  const groupIds = useFilterStore((s) => s.groupIds)
  const view = useDashboardViewStore((s) => s.view)
  const tab = useDashboardViewStore((s) => s.tab)

  // Blocks the emit effect's very first post-mount run. That run
  // would fire with the component's render-#1 closure (empty store,
  // because the hydrate `useLayoutEffect` below updates zustand via
  // its external-store path, which doesn't synchronously re-render
  // within the same commit). Without this guard we'd blank the URL
  // on mount: emit sees empty state vs URL with filters, writes ''.
  // The subsequent render (triggered by zustand's notification) then
  // re-runs emit with the hydrated closure and writes the canonical
  // URL — net result is two writes, one of which briefly clears the
  // URL. Skipping the initial run leaves canonicalization to the
  // render-#2 run.
  const isInitialMountRef = useRef(true)

  // ── Mount hydration ────────────────────────────────────────────
  // Reads the initial URL exactly once. `useLayoutEffect` so the
  // store update is flushed BEFORE the emit effect below runs on
  // the same commit — otherwise the emit effect sees initial (empty)
  // store state, encodes `""`, and briefly blanks a URL that had
  // valid filters. Subsequent popstate events handle back/forward;
  // store-driven changes handle user toggles.
  useLayoutEffect(() => {
    hydrateStoresFromUrl(window.location.pathname === DASHBOARD_PATH)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Popstate re-hydration ──────────────────────────────────────
  useEffect(() => {
    function handler(): void {
      hydrateStoresFromUrl(window.location.pathname === DASHBOARD_PATH)
    }
    window.addEventListener('popstate', handler)
    return () => window.removeEventListener('popstate', handler)
  }, [])

  // ── Store → URL emission ───────────────────────────────────────
  // Rebuilds the search string on every tracked-dep change and
  // compares to the live URL. Equal → no-op (blocks the mount-
  // hydration ping-pong). Different → `history.replaceState`.
  // Skips its first post-mount run (see isInitialMountRef) so the
  // closure-stale initial state doesn't briefly blank the URL.
  //
  // Page-local URL state short-circuit (PR-B T10 r1 fold): when
  // `isPageLocalUrlState` is true the route owns its own URL surface
  // (correlation: x / y / date_from / date_to / method). The encoder
  // here only knows about the global keys, so emitting on those
  // routes would strip the page-local params from the URL. The
  // page's own `replaceState` write keeps its surface in sync;
  // global filter-store toggles applied while on a page-local route
  // simply don't propagate to the URL until the user navigates
  // back to a route that participates in this sync.
  useEffect(() => {
    if (isInitialMountRef.current) {
      isInitialMountRef.current = false
      return
    }
    if (isPageLocalUrlState) return
    const urlState: UrlState = {
      dateFrom,
      dateTo,
      groupIds,
      view: isDashboard ? view : null,
      tab: isDashboard ? tab : null,
    }
    const next = urlStateSearchString(urlState)
    const current = readUrlSearch()
    if (next === current) return
    writeUrlSearch(next)
  }, [dateFrom, dateTo, groupIds, view, tab, isDashboard, isPageLocalUrlState, pathname])
}

// Expose the helper for tests that want to snapshot the encode step
// independently of the hook's effect lifecycle.
export { encodeUrlState, decodeUrlState }

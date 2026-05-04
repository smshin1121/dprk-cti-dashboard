/**
 * PeriodReadout — read-only mirror of the global FilterBar's date range.
 *
 * L7 contract: NO setter, NO input element, NO click-to-edit. Subscribes
 * to `useFilterStore` for `dateFrom` / `dateTo` (camelCase store fields
 * per Codex F3; URL/wire is `date_from` / `date_to`). The hint copy is
 * a text-only glyph — clicking it must not scroll, focus, or navigate.
 *
 * L8 heading row geometry: this component lives inside the dashboard
 * heading row at right-alignment. No card chrome on the component
 * itself; the heading row's flex container handles layout.
 *
 * Layer rule (L1): file lives under `apps/frontend/src/layout/`; it is
 * imported by `DashboardPage.tsx`. `Shell.tsx` MUST NOT import it
 * (Shell static-source guard at `__tests__/Shell.architectural-guard
 * .test.tsx` pins this contract).
 *
 * i18n: T7 hardcodes the user-visible strings ("Period", "All time",
 * "change in filter bar"). T11 swaps these to `dashboard.period.*` keys
 * once the i18n table grows.
 */

import { useEffect, useReducer, useRef } from 'react'
import { flushSync } from 'react-dom'

import { useFilterStore } from '../stores/filters'

const ALL_TIME_FALLBACK = 'All time'
const RANGE_SEPARATOR = '–'
const OPEN_BOUND_GLYPH = '…'

function formatRange(from: string | null, to: string | null): string {
  if (from === null && to === null) {
    return ALL_TIME_FALLBACK
  }
  const left = from ?? OPEN_BOUND_GLYPH
  const right = to ?? OPEN_BOUND_GLYPH
  return `${left} ${RANGE_SEPARATOR} ${right}`
}

export function PeriodReadout(): JSX.Element {
  // Subscribe to the filter store via a manual force-render that
  // flushSync's the commit. zustand v5's default `useStore` hook
  // goes through React's deferred scheduler, which means an external
  // setState doesn't reflect in the DOM synchronously — the live-
  // mirror contract assertion sees stale text. flushSync forces the
  // commit on the same tick as the store notification so the readout
  // never lags the FilterBar's date inputs. Comparator gate skips
  // forceRender when only non-mirrored fields (groupIds / tlpLevels)
  // change so unrelated filter toggles don't reflow the heading row.
  const [, forceRender] = useReducer((c: number) => c + 1, 0)
  const lastSnapshot = useRef<{ from: string | null; to: string | null }>({
    from: useFilterStore.getState().dateFrom,
    to: useFilterStore.getState().dateTo,
  })
  useEffect(() => {
    return useFilterStore.subscribe((state) => {
      if (
        state.dateFrom === lastSnapshot.current.from &&
        state.dateTo === lastSnapshot.current.to
      ) {
        return
      }
      lastSnapshot.current = { from: state.dateFrom, to: state.dateTo }
      flushSync(() => forceRender())
    })
  }, [])
  const { dateFrom, dateTo } = useFilterStore.getState()

  return (
    <div
      data-testid="period-readout"
      className="flex flex-col items-end gap-1"
    >
      <span
        data-testid="period-readout-label"
        className="text-[10px] font-cta uppercase tracking-caption text-ink-subtle"
      >
        Period
      </span>
      <div className="flex items-center gap-2 text-sm text-ink tabular-nums">
        <span data-testid="period-readout-value">
          {formatRange(dateFrom, dateTo)}
        </span>
        <span
          data-testid="period-readout-hint"
          className="flex items-center gap-1 text-xs text-ink-subtle"
        >
          <span aria-hidden>↑</span>
          change in filter bar
        </span>
      </div>
    </div>
  )
}

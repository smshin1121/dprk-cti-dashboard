/**
 * Phase 3 Slice 3 D-1 — CorrelationFilters T9 implementation.
 *
 * X / Y series pickers (catalog-driven disclosure dropdowns) and a
 * date-range pair (free-form ISO date inputs). Method toggle lives in
 * `CorrelationPage` because it drives chart-only state, not query-key
 * inputs — keeping the filter component free of method-state means
 * `pattern_shared_query_cache_multi_subscriber` re-renders cannot
 * accidentally branch on toggle.
 *
 * Dropdowns are simple disclosure pattern: a button with the current
 * label opens a list of option buttons. Native `<select>` would
 * collapse the X/Y interaction surface to a single click, but the
 * test contract pins per-option testids (`correlation-filter-y-option-<id>`)
 * which native select options do not expose deterministically under
 * happy-dom + user-event v14.
 */

import { useState } from 'react'

import type { CorrelationSeriesItem } from '../../../lib/api/schemas'

export interface CorrelationFiltersProps {
  catalog: CorrelationSeriesItem[]
  x: string
  y: string
  dateFrom: string | null
  dateTo: string | null
  onChangeX: (id: string) => void
  onChangeY: (id: string) => void
  onChangeDateFrom: (date: string | null) => void
  onChangeDateTo: (date: string | null) => void
}

function labelFor(catalog: CorrelationSeriesItem[], id: string): string {
  const hit = catalog.find((s) => s.id === id)
  return hit ? hit.label_en : id
}

interface SeriesPickerProps {
  axis: 'x' | 'y'
  selected: string
  catalog: CorrelationSeriesItem[]
  onPick: (id: string) => void
}

function SeriesPicker({ axis, selected, catalog, onPick }: SeriesPickerProps): JSX.Element {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative flex flex-col gap-1">
      <span className="text-xs font-cta uppercase tracking-caption text-ink-muted">
        {axis === 'x' ? 'X series' : 'Y series'}
      </span>
      <button
        type="button"
        data-testid={`correlation-filter-${axis}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="rounded-none border border-border-card bg-app px-3 py-1.5 text-left text-sm font-body text-ink hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {selected ? labelFor(catalog, selected) : `Pick ${axis.toUpperCase()}…`}
      </button>
      {open ? (
        <ul
          role="listbox"
          className="absolute top-full z-10 mt-1 flex flex-col rounded-none border border-border-card bg-surface shadow"
        >
          {catalog.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                data-testid={`correlation-filter-${axis}-option-${s.id}`}
                onClick={() => {
                  onPick(s.id)
                  setOpen(false)
                }}
                className="block w-full px-3 py-1.5 text-left text-sm text-ink hover:bg-app focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {s.label_en}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export function CorrelationFilters({
  catalog,
  x,
  y,
  dateFrom,
  dateTo,
  onChangeX,
  onChangeY,
  onChangeDateFrom,
  onChangeDateTo,
}: CorrelationFiltersProps): JSX.Element {
  return (
    <div className="flex flex-wrap items-end gap-4">
      <SeriesPicker axis="x" selected={x} catalog={catalog} onPick={onChangeX} />
      <SeriesPicker axis="y" selected={y} catalog={catalog} onPick={onChangeY} />

      <label className="flex flex-col gap-1">
        <span className="text-xs font-cta uppercase tracking-caption text-ink-muted">
          Date from
        </span>
        <input
          type="text"
          inputMode="numeric"
          placeholder="YYYY-MM-DD"
          data-testid="correlation-filter-date-from"
          value={dateFrom ?? ''}
          onChange={(e) => onChangeDateFrom(e.target.value || null)}
          className="rounded-none border border-border-card bg-app px-3 py-1.5 text-sm font-body text-ink hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs font-cta uppercase tracking-caption text-ink-muted">
          Date to
        </span>
        <input
          type="text"
          inputMode="numeric"
          placeholder="YYYY-MM-DD"
          data-testid="correlation-filter-date-to"
          value={dateTo ?? ''}
          onChange={(e) => onChangeDateTo(e.target.value || null)}
          className="rounded-none border border-border-card bg-app px-3 py-1.5 text-sm font-body text-ink hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </label>
    </div>
  )
}

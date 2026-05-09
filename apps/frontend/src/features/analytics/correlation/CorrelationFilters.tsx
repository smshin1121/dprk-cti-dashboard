/**
 * Phase 3 Slice 3 D-1 — CorrelationFilters (T9 base + T11 i18n keys).
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
 *
 * Date inputs use a draft + commit pattern: every keystroke updates
 * a local draft string but only commits to the parent (and therefore
 * to the URL + the React Query cache key) when the value is empty
 * or matches the canonical `YYYY-MM-DD` ISO shape. Without this gate
 * a real-world `2024-01-01` typing pass would issue 9 partial
 * fetches (`?date_from=2`, `?date_from=20`, …) that the BE would
 * reject as 422 and that would pollute the React Query cache with
 * malformed keys. Tests pass because user-event types char-by-char;
 * only the final keystroke matches the regex and produces the
 * single committed value the URL-write tests assert against.
 */

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { CorrelationSeriesItem } from '../../../lib/api/schemas'

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

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
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  const seriesLabel =
    axis === 'x'
      ? t('correlation.filters.xSeriesLabel')
      : t('correlation.filters.ySeriesLabel')
  const pickerPlaceholder =
    axis === 'x'
      ? t('correlation.filters.xPickerPlaceholder')
      : t('correlation.filters.yPickerPlaceholder')

  return (
    <div className="relative flex flex-col gap-1">
      <span className="text-xs font-cta uppercase tracking-caption text-ink-muted">
        {seriesLabel}
      </span>
      <button
        type="button"
        data-testid={`correlation-filter-${axis}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="rounded-none border border-border-card bg-app px-3 py-1.5 text-left text-sm font-body text-ink hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring"
      >
        {selected ? labelFor(catalog, selected) : pickerPlaceholder}
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

interface DraftDateInputProps {
  testId: string
  label: string
  value: string | null
  onCommit: (date: string | null) => void
}

function DraftDateInput({ testId, label, value, onCommit }: DraftDateInputProps): JSX.Element {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<string>(value ?? '')

  // Re-sync draft when the committed value changes from above (URL
  // hydrate, programmatic clear). Comparison guards against the
  // self-emit ping-pong: when the input itself drove the commit,
  // value === draft, so this effect is a no-op.
  useEffect(() => {
    setDraft((prev) => (prev === (value ?? '') ? prev : value ?? ''))
  }, [value])

  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-cta uppercase tracking-caption text-ink-muted">
        {label}
      </span>
      <input
        type="text"
        inputMode="numeric"
        placeholder={t('correlation.filters.datePlaceholder')}
        data-testid={testId}
        value={draft}
        onChange={(e) => {
          const next = e.target.value
          setDraft(next)
          if (next === '') {
            onCommit(null)
          } else if (ISO_DATE.test(next)) {
            onCommit(next)
          }
          // Partial values (e.g. "2024-01-0") update the visible
          // draft but do NOT propagate — the React Query cache key
          // and the URL stay on the last committed value.
        }}
        className="rounded-none border border-border-card bg-app px-3 py-1.5 text-sm font-body text-ink hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring"
      />
    </label>
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
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap items-end gap-4">
      <SeriesPicker axis="x" selected={x} catalog={catalog} onPick={onChangeX} />
      <SeriesPicker axis="y" selected={y} catalog={catalog} onPick={onChangeY} />
      <DraftDateInput
        testId="correlation-filter-date-from"
        label={t('correlation.filters.dateFromLabel')}
        value={dateFrom}
        onCommit={onChangeDateFrom}
      />
      <DraftDateInput
        testId="correlation-filter-date-to"
        label={t('correlation.filters.dateToLabel')}
        value={dateTo}
        onCommit={onChangeDateTo}
      />
    </div>
  )
}

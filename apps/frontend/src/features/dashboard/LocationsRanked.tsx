/**
 * LocationsRanked — top-N incident locations as a ranked horizontal
 * bar list. PR #23 §6.C C10 (lazarus.day "Locations" parity, SHOULD
 * per plan §4 — accessibility companion to `WorldMap` for users who
 * need a sortable list view of the same data).
 *
 * Data: `useGeo()` — the SAME hook `WorldMap` consumes. React Query
 * shares the `['analytics', 'geo', filters]` cache slot across both
 * subscribers, so mounting `LocationsRanked` next to `WorldMap` does
 * NOT trigger an extra `/analytics/geo` request. (Pinned by the
 * `LocationsRanked.test.tsx::shares /analytics/geo cache with
 * WorldMap` test.)
 *
 * BE order:
 *   `/analytics/geo` returns countries sorted by `count DESC,
 *   iso2 ASC` (see `analytics_aggregator.py::compute_geo`). The widget
 *   consumes the BE order verbatim and slices the head-N rows; no
 *   client-side re-sort.
 *
 * Visual:
 *   Same CSS bar idiom as `SectorBreakdown` (width = count /
 *   max_count * 100%). No Recharts → no ResizeObserver fragility.
 *
 * Four render states (TrendChart / SectorBreakdown parity).
 */

import { useTranslation } from 'react-i18next'

import { useGeo } from '../analytics/useGeo'
import { cn } from '../../lib/utils'

const TOP_N = 10

export function LocationsRanked(): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useGeo()

  if (isLoading) {
    return (
      <div
        data-testid="locations-ranked-loading"
        role="status"
        aria-busy="true"
        className="h-64 animate-pulse rounded border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid="locations-ranked-error"
        role="alert"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid="locations-ranked-retry"
          onClick={() => void refetch()}
          className={cn(
            'rounded border border-border-card bg-app px-3 py-1.5 text-xs text-ink',
            'hover:border-signal focus:outline-none focus:ring-2 focus:ring-signal',
          )}
        >
          {t('list.retry')}
        </button>
      </div>
    )
  }

  // BE arrives sorted count DESC + iso2 ASC; slice head-10.
  const countries = data?.countries.slice(0, TOP_N) ?? []

  if (countries.length === 0) {
    return (
      <section
        data-testid="locations-ranked-empty"
        className="flex h-64 flex-col items-center justify-center gap-2 rounded border border-border-card bg-surface p-6"
      >
        <h3 className="text-sm font-semibold text-ink">
          {t('dashboard.locationsRanked.title')}
        </h3>
        <p className="text-sm text-ink-muted">
          {t('dashboard.locationsRanked.empty')}
        </p>
      </section>
    )
  }

  // Head row's count is the max (BE sort guarantees this); coerce to
  // 1 if the head somehow reports 0 to avoid a divide-by-zero ratio.
  const maxCount = Math.max(countries[0].count, 1)

  return (
    <section
      data-testid="locations-ranked"
      aria-labelledby="locations-ranked-heading"
      className="rounded border border-border-card bg-surface p-4"
    >
      <h3
        id="locations-ranked-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t('dashboard.locationsRanked.title')}
      </h3>
      <ol
        data-testid="locations-ranked-items"
        className="flex flex-col gap-2"
      >
        {countries.map((country) => {
          const ratio = (country.count / maxCount) * 100
          return (
            <li
              key={country.iso2}
              data-testid={`locations-ranked-item-${country.iso2}`}
              data-iso2={country.iso2}
              data-count={country.count}
              className="text-sm"
            >
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-ink">{country.iso2}</span>
                <span className="font-mono text-xs text-ink-muted">
                  {country.count}{' '}
                  <span className="text-ink-subtle">
                    {t('dashboard.locationsRanked.incidentsSuffix')}
                  </span>
                </span>
              </div>
              <div className="mt-1 h-1.5 w-full overflow-hidden rounded bg-app">
                <div
                  data-testid={`locations-ranked-bar-${country.iso2}`}
                  role="presentation"
                  aria-hidden="true"
                  className="h-full bg-signal"
                  style={{ width: `${ratio}%` }}
                />
              </div>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

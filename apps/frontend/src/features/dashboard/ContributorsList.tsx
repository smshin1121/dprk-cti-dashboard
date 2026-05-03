/**
 * ContributorsList — "Leading Contributors" panel (lazarus.day
 * parity). PR #23 §6.C C6.
 *
 * Data: `useDashboardSummary().top_sources` (PR #23 §6.A C2). Shares
 * the same cache slot as KPIStrip / MotivationDonut / YearBar /
 * GroupsMiniList / SectorBreakdown — mounting all six fires ONE
 * `/dashboard/summary` request.
 *
 * Row shape (per plan §6.C C6): `{source_name, report_count,
 * latest_report_date}` — the BE also exposes `source_id` for the
 * stable React key + future deep-link target.
 *
 * Click navigation:
 * Plan §6.C C13 wires a row click → navigate to `/reports` with
 * `sources=<name>` pre-filled in filterStore. That requires the
 * SourcePicker (C12) which adds a `sources` field to filterStore.
 * Until C12/C13 land, rows render as plain non-interactive entries
 * (a TODO comment marks the future Link target). The parity gap
 * lazarus.day calls "Leading Contributors" is closed visually by
 * showing the contributor list; the deep-link is a follow-up commit.
 *
 * Four render states (TrendChart / GroupsMiniList parity).
 */

import { useTranslation } from 'react-i18next'

import { cn } from '../../lib/utils'
import { useDashboardSummary } from './useDashboardSummary'

export function ContributorsList(): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useDashboardSummary()

  if (isLoading) {
    return (
      <div
        data-testid="contributors-list-loading"
        role="status"
        aria-busy="true"
        className="h-64 animate-pulse rounded border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid="contributors-list-error"
        role="alert"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid="contributors-list-retry"
          onClick={() => void refetch()}
          className={cn(
            'rounded border border-border-card bg-app px-3 py-1.5 text-xs text-ink',
            'hover:border-signal focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          {t('list.retry')}
        </button>
      </div>
    )
  }

  const sources = data?.top_sources ?? []

  if (sources.length === 0) {
    return (
      <section
        data-testid="contributors-list-empty"
        className="flex h-64 flex-col items-center justify-center gap-2 rounded border border-border-card bg-surface p-6"
      >
        <h3 className="text-sm font-semibold text-ink">
          {t('dashboard.contributorsList.title')}
        </h3>
        <p className="text-sm text-ink-muted">
          {t('dashboard.contributorsList.empty')}
        </p>
      </section>
    )
  }

  return (
    <section
      data-testid="contributors-list"
      aria-labelledby="contributors-list-heading"
      className="rounded border border-border-card bg-surface p-4"
    >
      <h3
        id="contributors-list-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t('dashboard.contributorsList.title')}
      </h3>
      <ol
        data-testid="contributors-list-items"
        className="divide-y divide-border-card"
      >
        {sources.map((source) => (
          <li
            key={source.source_id}
            data-testid={`contributors-list-item-${source.source_id}`}
            data-source-id={source.source_id}
            data-source-name={source.source_name}
            data-report-count={source.report_count}
            className="flex items-center justify-between gap-3 px-1 py-2 text-sm"
          >
            {/* TODO(C13): wrap in <Link to="/reports"> after C12
                adds `sources` to filterStore + the row-click handler
                pre-fills the source filter. Plain text for now keeps
                the parity-visible widget shippable without coupling
                to FilterBar work. */}
            <div className="min-w-0 flex-1">
              <span className="block truncate font-medium text-ink">
                {source.source_name}
              </span>
              {source.latest_report_date != null && (
                <span className="text-xs text-ink-muted">
                  {t('dashboard.contributorsList.latestPrefix')}{' '}
                  {source.latest_report_date}
                </span>
              )}
            </div>
            <span className="shrink-0 rounded bg-app px-2 py-0.5 text-xs font-mono text-ink-muted">
              {source.report_count}{' '}
              <span className="text-ink-subtle">
                {t('dashboard.contributorsList.reportsSuffix')}
              </span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  )
}

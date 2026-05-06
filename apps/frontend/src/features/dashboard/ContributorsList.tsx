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

import { RankedRowWithShareBar } from '../../layout/RankedRowWithShareBar'
import { cn } from '../../lib/utils'
import { useDashboardSummary } from './useDashboardSummary'

function avatarInitials(name: string): string {
  // Two-char initials from a contributor / source name. Falls back to
  // first 2 chars when the name has only one word.
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }
  return name.slice(0, 2).toUpperCase()
}

export function ContributorsList(): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useDashboardSummary()

  if (isLoading) {
    return (
      <div
        data-testid="contributors-list-loading"
        role="status"
        aria-busy="true"
        className="h-64 animate-pulse rounded-none border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid="contributors-list-error"
        role="alert"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded-none border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid="contributors-list-retry"
          onClick={() => void refetch()}
          className={cn(
            'rounded-none border border-border-card bg-app px-3 py-1.5 text-xs font-cta uppercase tracking-cta text-ink',
            'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          {t('list.retry')}
        </button>
      </div>
    )
  }

  const sources = data?.top_sources ?? []
  // Head row's report_count is the max (BE sorts top_sources by
  // report_count DESC); coerce to 1 if the head somehow reports 0
  // to avoid a divide-by-zero.
  const maxReportCount =
    sources.length > 0 ? Math.max(sources[0].report_count, 1) : 1

  if (sources.length === 0) {
    return (
      <section
        data-testid="contributors-list-empty"
        className="flex h-64 flex-col items-center justify-center gap-2 rounded-none border border-border-card bg-surface p-6"
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
      className="rounded-none border border-border-card bg-surface p-4"
    >
      <h3
        id="contributors-list-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t('dashboard.contributorsList.title')}
      </h3>
      <ol data-testid="contributors-list-items" className="flex flex-col">
        {sources.map((source) => {
          const ratio = (source.report_count / maxReportCount) * 100
          return (
            <li
              key={source.source_id}
              data-testid={`contributors-list-item-${source.source_id}`}
              data-source-id={source.source_id}
              data-source-name={source.source_name}
              data-report-count={source.report_count}
            >
              {/* TODO(C13): wrap in <Link to="/reports"> after C12
                  adds `sources` to filterStore + the row-click handler
                  pre-fills the source filter. */}
              <RankedRowWithShareBar
                avatarText={avatarInitials(source.source_name)}
                name={source.source_name}
                sub={
                  source.latest_report_date != null
                    ? `${t('dashboard.contributorsList.latestPrefix')} ${source.latest_report_date}`
                    : undefined
                }
                value={`${source.report_count} ${t('dashboard.contributorsList.reportsSuffix')}`}
                shareBarPct={ratio}
                barFillTestId={`contributors-list-bar-${source.source_id}`}
              />
            </li>
          )
        })}
      </ol>
    </section>
  )
}

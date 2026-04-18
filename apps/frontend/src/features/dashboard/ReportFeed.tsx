/**
 * Compact latest-reports feed — design doc §4.2 area [E] panel.
 * Plan D2 + D9 (PR #13 Group I).
 *
 * Data: `useReportsList({ limit })` — the SAME PR #12 Group F hook
 * the `/reports` route consumes. Contract preservation is a review
 * invariant:
 *
 *   - We call `useReportsList` with the existing `UseReportsListArgs`
 *     (`cursor?` + `limit?`). No new params added to the hook.
 *   - We pass only `limit` — no `cursor`, so the BE returns the
 *     first (latest) keyset page. The `/reports` route stack-managed
 *     pagination is unaffected.
 *   - We do not mutate the BE ordering (keyset by `published desc`);
 *     the feed renders what the BE returns in the order returned.
 *
 * If a future change needs a shorter per-row shape, it happens here
 * — not inside `useReportsList` — to keep the list route in PR #12
 * immune to dashboard-specific edits.
 *
 * Four render states (review invariant per user):
 *   - loading    → skeleton
 *   - error      → inline error card + retry
 *   - empty      → dedicated empty card
 *   - populated  → compact list of report rows
 */

import { useTranslation } from 'react-i18next'

import { useReportsList } from '../reports/useReportsList'
import { cn } from '../../lib/utils'

const FEED_SIZE = 5

export function ReportFeed(): JSX.Element {
  const { t } = useTranslation()
  // `limit` is the ONLY param we use from the PR #12 hook contract.
  // `cursor` is intentionally omitted — the feed always shows the
  // latest page, no Prev/Next affordance.
  const { data, isLoading, isError, refetch } = useReportsList({
    limit: FEED_SIZE,
  })

  if (isLoading) {
    return (
      <div
        data-testid="report-feed-loading"
        role="status"
        aria-busy="true"
        className="h-64 animate-pulse rounded border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid="report-feed-error"
        role="alert"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid="report-feed-retry"
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

  const items = data?.items ?? []

  if (items.length === 0) {
    return (
      <section
        data-testid="report-feed-empty"
        className="flex h-64 flex-col items-center justify-center gap-2 rounded border border-border-card bg-surface p-6"
      >
        <h3 className="text-sm font-semibold text-ink">
          {t('dashboard.reportFeed.title')}
        </h3>
        <p className="text-sm text-ink-muted">{t('dashboard.reportFeed.empty')}</p>
      </section>
    )
  }

  return (
    <section
      data-testid="report-feed"
      aria-labelledby="report-feed-heading"
      className="rounded border border-border-card bg-surface p-4"
    >
      <h3
        id="report-feed-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t('dashboard.reportFeed.title')}
      </h3>
      <ul data-testid="report-feed-items" className="divide-y divide-border-card">
        {items.map((report) => (
          <li
            key={report.id}
            data-testid={`report-feed-item-${report.id}`}
            data-report-id={report.id}
            className="flex flex-col gap-1 px-1 py-2 text-sm"
          >
            <a
              href={report.url}
              target="_blank"
              rel="noreferrer"
              className="truncate font-medium text-signal hover:underline"
            >
              {report.title}
            </a>
            <div className="flex items-center gap-3 text-xs text-ink-muted">
              <span className="font-mono">{report.published}</span>
              <span>·</span>
              <span className="truncate">{report.source_name ?? '—'}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

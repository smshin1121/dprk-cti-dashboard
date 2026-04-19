/**
 * Similar-reports live panel — PR #14 Group F (plan D2 + D8 + D10).
 *
 * Mounts on `ReportDetailPage` with the current report's id; replaces
 * the PR #13 dashboard-scoped static stub (`features/dashboard/
 * SimilarReports.tsx`, deleted this commit).
 *
 * Four render states:
 *   - loading   → skeleton
 *   - error     → inline error + retry
 *   - D10 empty → distinct empty-state card (no fake fallback)
 *   - populated → list of similar-report summaries, each a
 *                 `<Link to="/reports/:id">` row
 *
 * D10 empty contract (critical):
 *   The BE returns `{items: []}` with 200 OK when the source report
 *   has no embedding OR when the kNN search returns zero rows after
 *   self-exclusion. The panel MUST render an honest empty card — no
 *   "recent N" stand-in, no shared-tag fallback. The distinction
 *   between error and empty is first-class: `items.length === 0` AND
 *   `query.isSuccess` means "empty, successfully fetched, nothing to
 *   show." Pinned by `SimilarReportsPanel.test.tsx`.
 *
 * D8 cache scope:
 *   `useSimilarReports(reportId, k)` keys on `(reportId, k)` only.
 *   No FilterBar state participates — filter toggles do not refetch.
 *   Source-report change (navigating to a different /reports/:id)
 *   opens a new cache slot.
 *
 * Score display: cosine similarity in `[0, 1]` rendered as a
 * percentage (`0.87` → `87%`). The BE emits `1 - distance` so higher
 * is more similar; see the `score` field on `SimilarReportEntry`.
 */

import { Link } from 'react-router-dom'

import { useSimilarReports } from './useSimilarReports'

interface SimilarReportsPanelProps {
  reportId: number
  /** Optional override; defaults to `SIMILAR_K_DEFAULT` via the hook. */
  k?: number
}

export function SimilarReportsPanel({
  reportId,
  k,
}: SimilarReportsPanelProps): JSX.Element | null {
  const query = useSimilarReports(reportId, k)

  // Invalid source id — the parent should not mount the panel in
  // this case (detail page only renders with a valid report.id), but
  // if it does, render nothing rather than dragging the hook's
  // disabled state through the empty-card branch.
  if (!Number.isInteger(reportId) || reportId <= 0) {
    return null
  }

  if (query.isLoading) {
    return (
      <section
        data-testid="similar-reports-loading"
        role="status"
        aria-busy="true"
        className="h-48 animate-pulse rounded border border-border-card bg-surface"
      />
    )
  }

  if (query.isError) {
    return (
      <section
        data-testid="similar-reports-error"
        role="alert"
        className="flex flex-col items-center justify-center gap-3 rounded border border-border-card bg-surface p-6"
      >
        <h2 className="text-sm font-semibold text-ink">Similar reports</h2>
        <p className="text-sm text-ink-muted">
          Failed to load similar reports.
        </p>
        <button
          type="button"
          data-testid="similar-reports-retry"
          onClick={() => void query.refetch()}
          className="rounded border border-border-card bg-app px-3 py-1.5 text-xs text-ink hover:border-signal focus:outline-none focus:ring-2 focus:ring-signal"
        >
          Retry
        </button>
      </section>
    )
  }

  const items = query.data?.items ?? []

  // D10 empty contract — distinct state, NOT an error. Renders an
  // honest "no similar reports" card; never injects a fake / heuristic
  // fallback (no recent-N stand-in, no shared-tag overlap).
  if (items.length === 0) {
    return (
      <section
        data-testid="similar-reports-empty"
        data-source-report-id={reportId}
        aria-labelledby="similar-reports-heading"
        className="rounded border border-border-card bg-surface p-4"
      >
        <h2
          id="similar-reports-heading"
          className="mb-2 text-sm font-semibold text-ink"
        >
          Similar reports
        </h2>
        <p className="text-sm text-ink-muted">
          No similar reports found for this report.
        </p>
      </section>
    )
  }

  return (
    <section
      data-testid="similar-reports"
      data-source-report-id={reportId}
      aria-labelledby="similar-reports-heading"
      className="rounded border border-border-card bg-surface p-4"
    >
      <h2
        id="similar-reports-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        Similar reports
      </h2>
      <ul className="divide-y divide-border-card">
        {items.map((item) => (
          <li
            key={item.report.id}
            data-testid={`similar-reports-item-${item.report.id}`}
            data-report-id={item.report.id}
            data-score={item.score}
            className="flex flex-col gap-1 px-1 py-2 text-sm"
          >
            <div className="flex items-start justify-between gap-3">
              <Link
                to={`/reports/${item.report.id}`}
                className="truncate font-medium text-signal hover:underline"
              >
                {item.report.title}
              </Link>
              <span
                data-testid={`similar-reports-score-${item.report.id}`}
                className="shrink-0 rounded bg-app px-2 py-0.5 text-xs font-mono text-ink-muted"
              >
                {formatScore(item.score)}
              </span>
            </div>
            <div className="flex items-center gap-3 text-xs text-ink-muted">
              <span className="font-mono">{item.report.published}</span>
              <span>·</span>
              <span className="truncate">{item.report.source_name ?? '—'}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * Format `[0, 1]` cosine similarity as a compact percentage.
 * `0.874` → `"87%"`, `1.0` → `"100%"`, `0.0` → `"0%"`. Using
 * `Math.round` keeps the display stable against tiny numeric jitter
 * while preserving analyst-legibility at percent resolution.
 */
function formatScore(score: number): string {
  return `${Math.round(score * 100)}%`
}

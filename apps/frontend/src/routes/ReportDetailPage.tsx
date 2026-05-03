/**
 * `/reports/:id` — protected report detail view. PR #14 Group E
 * (plan D1 + D9 + D11).
 *
 * Render states:
 *   - malformed id → NotFound panel (no fetch)
 *   - loading → skeleton
 *   - 404 → NotFound panel
 *   - other error → error card with retry
 *   - populated → report fields + linked_incidents section
 *
 * D11 navigation contract:
 *   `linked_incidents` rows link to `/incidents/:id`. The BE
 *   aggregator sources these via `incident_sources` (migration 0001
 *   M:N), capped at `REPORT_DETAIL_INCIDENTS_CAP` (10). No further
 *   nested links — per D9's "no recursive nesting" rule, a linked
 *   incident row is a summary, not a full drill-through.
 *
 * `SimilarReportsPanel` (plan D2 + D8 + D10) mounts at the bottom of
 * this page, keyed on `report.id`. The panel renders its own loading
 * / error / D10-empty / populated states; a failing similarity fetch
 * degrades only that panel, not the rest of the report detail.
 */

import { Link, useParams } from 'react-router-dom'

import { useReportDetail } from '../features/detail/useReportDetail'
import { SimilarReportsPanel } from '../features/similar/SimilarReportsPanel'
import { ApiError } from '../lib/api'
import { parseDetailId } from './detailParams'

export function ReportDetailPage(): JSX.Element {
  const { id: idParam } = useParams<{ id: string }>()
  const id = parseDetailId(idParam)
  // Always call the hook (rules of hooks). When id is null we pass
  // 0, which trips the hook's `enabled: Number.isInteger && > 0`
  // guard and no fetch fires.
  const query = useReportDetail(id ?? 0)

  if (id == null) {
    return <NotFoundPanel testId="report-detail-notfound" kind="report" />
  }

  if (query.isLoading) {
    return (
      <section
        data-testid="report-detail-loading"
        role="status"
        aria-busy="true"
        className="m-6 h-64 animate-pulse rounded-none border border-border-card bg-surface"
      />
    )
  }

  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 404) {
      return <NotFoundPanel testId="report-detail-notfound" kind="report" />
    }
    return (
      <ErrorPanel
        testId="report-detail-error"
        onRetry={() => void query.refetch()}
      />
    )
  }

  const report = query.data!
  return (
    <section
      data-testid="report-detail-page"
      data-report-id={report.id}
      aria-labelledby="report-detail-heading"
      className="flex flex-col gap-6 p-6"
    >
      <header className="flex flex-col gap-2">
        <h1
          id="report-detail-heading"
          className="text-xl font-semibold text-ink"
        >
          {report.title}
        </h1>
        <div className="flex flex-wrap items-center gap-3 text-xs text-ink-muted">
          <span className="font-mono">{report.published}</span>
          <span>·</span>
          <span>{report.source_name ?? '—'}</span>
          {report.tlp != null && (
            <>
              <span>·</span>
              <span className="font-mono">TLP:{report.tlp}</span>
            </>
          )}
          {report.lang != null && (
            <>
              <span>·</span>
              <span className="font-mono">{report.lang}</span>
            </>
          )}
        </div>
      </header>

      {report.summary != null && (
        <p
          data-testid="report-detail-summary"
          className="text-sm text-ink"
        >
          {report.summary}
        </p>
      )}

      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        <DLEntry label="Reliability" value={report.reliability ?? '—'} />
        <DLEntry label="Credibility" value={report.credibility ?? '—'} />
        <DLEntry
          label="Source"
          value={
            <a
              href={report.url}
              target="_blank"
              rel="noreferrer"
              data-testid="report-detail-external"
              className="text-signal hover:underline"
            >
              {report.url}
            </a>
          }
        />
        {report.tags.length > 0 && (
          <DLEntry label="Tags" value={report.tags.join(', ')} />
        )}
        {report.codenames.length > 0 && (
          <DLEntry label="Codenames" value={report.codenames.join(', ')} />
        )}
        {report.techniques.length > 0 && (
          <DLEntry
            label="Techniques"
            value={report.techniques.join(', ')}
          />
        )}
      </dl>

      {/* D11 — linked_incidents summaries derived from incident_sources
          M:N join, capped at REPORT_DETAIL_INCIDENTS_CAP (10). Each
          row links to /incidents/:id. No deeper nesting (D9). */}
      {report.linked_incidents.length > 0 && (
        <section
          data-testid="report-detail-linked-incidents"
          aria-labelledby="linked-incidents-heading"
          className="rounded border border-border-card bg-surface p-4"
        >
          <h2
            id="linked-incidents-heading"
            className="mb-3 text-sm font-semibold text-ink"
          >
            Linked incidents
          </h2>
          <ul className="divide-y divide-border-card">
            {report.linked_incidents.map((li) => (
              <li
                key={li.id}
                data-testid={`report-detail-linked-incident-${li.id}`}
                data-incident-id={li.id}
                className="flex items-center justify-between gap-3 px-1 py-2 text-sm"
              >
                <Link
                  to={`/incidents/${li.id}`}
                  className="truncate font-medium text-signal hover:underline"
                >
                  {li.title}
                </Link>
                <span className="shrink-0 font-mono text-xs text-ink-muted">
                  {li.reported ?? '—'}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Plan D2 + D8 + D10 — live similar-reports panel, keyed on
          `report.id`. Panel owns its own loading / error / empty /
          populated states so a similarity failure does not cascade
          into the rest of the detail page. */}
      <SimilarReportsPanel reportId={report.id} />
    </section>
  )
}

interface DLEntryProps {
  label: string
  value: React.ReactNode
}

function DLEntry({ label, value }: DLEntryProps): JSX.Element {
  return (
    <div className="flex flex-col">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="text-sm text-ink">{value}</dd>
    </div>
  )
}

interface NotFoundPanelProps {
  testId: string
  kind: 'report' | 'incident' | 'actor'
}

export function NotFoundPanel({ testId, kind }: NotFoundPanelProps): JSX.Element {
  const label = kind === 'report' ? 'Report' : kind === 'incident' ? 'Incident' : 'Actor'
  return (
    <section
      data-testid={testId}
      className="m-6 rounded-none border border-border-card bg-surface p-5"
    >
      <h1 className="text-lg font-semibold">{label} not found</h1>
      <p className="mt-2 text-sm text-ink-muted">
        The {label.toLowerCase()} you&apos;re looking for doesn&apos;t
        exist, or the link is malformed.
      </p>
    </section>
  )
}

interface ErrorPanelProps {
  testId: string
  onRetry: () => void
}

export function ErrorPanel({ testId, onRetry }: ErrorPanelProps): JSX.Element {
  return (
    <section
      data-testid={testId}
      role="alert"
      className="m-6 flex flex-col items-center justify-center gap-3 rounded-none border border-border-card bg-surface p-6"
    >
      <p className="text-sm text-ink-muted">
        Failed to load. Retry or pick another entry from the nav.
      </p>
      <button
        type="button"
        data-testid={`${testId}-retry`}
        onClick={onRetry}
        className="rounded-none border border-border-card bg-app px-3 py-1.5 text-xs font-cta uppercase tracking-cta text-ink hover:border-signal focus:outline-none focus:ring-2 focus:ring-ring"
      >
        Retry
      </button>
    </section>
  )
}

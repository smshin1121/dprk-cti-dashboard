/**
 * `/incidents/:id` — protected incident detail view. PR #14 Group E
 * (plan D1 + D9 + D11).
 *
 * D11 navigation contract:
 *   `linked_reports` rows link to `/reports/:id`. The BE aggregator
 *   sources these via `incident_sources` (migration 0001 M:N —
 *   bidirectional with the report detail page's linked_incidents
 *   traversal), capped at `INCIDENT_DETAIL_REPORTS_CAP` (20). Each
 *   row is a summary (`{id, title, url, published, source_name}`);
 *   no further nesting per D9.
 */

import { Link, useParams } from 'react-router-dom'

import { useIncidentDetail } from '../features/detail/useIncidentDetail'
import { ApiError } from '../lib/api'
import { parseDetailId } from './detailParams'
import { ErrorPanel, NotFoundPanel } from './ReportDetailPage'

export function IncidentDetailPage(): JSX.Element {
  const { id: idParam } = useParams<{ id: string }>()
  const id = parseDetailId(idParam)
  const query = useIncidentDetail(id ?? 0)

  if (id == null) {
    return <NotFoundPanel testId="incident-detail-notfound" kind="incident" />
  }

  if (query.isLoading) {
    return (
      <section
        data-testid="incident-detail-loading"
        role="status"
        aria-busy="true"
        className="m-6 h-64 animate-pulse rounded-lg border border-border-card bg-surface"
      />
    )
  }

  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 404) {
      return <NotFoundPanel testId="incident-detail-notfound" kind="incident" />
    }
    return (
      <ErrorPanel
        testId="incident-detail-error"
        onRetry={() => void query.refetch()}
      />
    )
  }

  const incident = query.data!
  return (
    <section
      data-testid="incident-detail-page"
      data-incident-id={incident.id}
      aria-labelledby="incident-detail-heading"
      className="flex flex-col gap-6 p-6"
    >
      <header className="flex flex-col gap-2">
        <h1
          id="incident-detail-heading"
          className="text-xl font-semibold text-ink"
        >
          {incident.title}
        </h1>
        <div className="flex flex-wrap items-center gap-3 text-xs text-ink-muted">
          <span className="font-mono">{incident.reported ?? '—'}</span>
          {incident.attribution_confidence != null && (
            <>
              <span>·</span>
              <span>{incident.attribution_confidence}</span>
            </>
          )}
          {incident.est_loss_usd != null && (
            <>
              <span>·</span>
              <span className="font-mono">
                ${incident.est_loss_usd.toLocaleString('en-US')}
              </span>
            </>
          )}
        </div>
      </header>

      {incident.description != null && (
        <p
          data-testid="incident-detail-description"
          className="text-sm text-ink"
        >
          {incident.description}
        </p>
      )}

      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        {incident.motivations.length > 0 && (
          <DLEntry
            label="Motivations"
            value={incident.motivations.join(', ')}
          />
        )}
        {incident.sectors.length > 0 && (
          <DLEntry label="Sectors" value={incident.sectors.join(', ')} />
        )}
        {incident.countries.length > 0 && (
          <DLEntry label="Countries" value={incident.countries.join(', ')} />
        )}
      </dl>

      {/* D11 — linked_reports summaries via incident_sources M:N,
          capped at INCIDENT_DETAIL_REPORTS_CAP (20). Each row links
          to /reports/:id; the external URL is reachable via the
          report detail page, not from this list. */}
      {incident.linked_reports.length > 0 && (
        <section
          data-testid="incident-detail-linked-reports"
          aria-labelledby="linked-reports-heading"
          className="rounded border border-border-card bg-surface p-4"
        >
          <h2
            id="linked-reports-heading"
            className="mb-3 text-sm font-semibold text-ink"
          >
            Linked reports
          </h2>
          <ul className="divide-y divide-border-card">
            {incident.linked_reports.map((lr) => (
              <li
                key={lr.id}
                data-testid={`incident-detail-linked-report-${lr.id}`}
                data-report-id={lr.id}
                className="flex flex-col gap-1 px-1 py-2 text-sm"
              >
                <Link
                  to={`/reports/${lr.id}`}
                  className="truncate font-medium text-signal hover:underline"
                >
                  {lr.title}
                </Link>
                <div className="flex items-center gap-3 text-xs text-ink-muted">
                  <span className="font-mono">{lr.published}</span>
                  <span>·</span>
                  <span className="truncate">{lr.source_name ?? '—'}</span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
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

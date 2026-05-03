/**
 * Actor → linked-reports panel — PR #15 Phase 3 slice 2 Group E
 * (plan D13 + D15 + D18).
 *
 * Mounts on `ActorDetailPage` below the codenames section with the
 * current actor's id. Consumes `useActorReports(actorId)`; the page
 * only mounts this panel inside its populated render branch so the
 * panel's own fetch never races the detail fetch.
 *
 * Four render states (mirrors `SimilarReportsPanel` exactly):
 *   - loading   → skeleton
 *   - error     → inline error + retry
 *   - D15 empty → distinct empty-state card
 *                 (no fake "recent N" fallback, no shared-tag stand-in)
 *   - populated → list of report summaries, each a
 *                 `<Link to="/reports/:id">` row
 *
 * D13 scope:
 *   Keyed on `actorId` only. No FilterBar state. TLP / groupIds /
 *   dateFrom toggles do NOT refetch — pinned by
 *   `useActorReports.test.tsx`.
 *
 * D15 empty contract (critical):
 *   The BE returns `{items: [], next_cursor: null}` with 200 OK when
 *   the actor exists but (b) has no codenames / (c) has codenames
 *   without report_codenames rows / (d) date filter excludes
 *   everything. All three branches render the same honest empty card
 *   — no heuristic fallback. The distinction between error and empty
 *   is first-class: `items.length === 0 && query.isSuccess` means
 *   "empty, successfully fetched, nothing to show." Pinned by
 *   `ActorLinkedReportsPanel.test.tsx`.
 *
 * D18 scope:
 *   This component is ONLY imported by `ActorDetailPage.tsx`. No
 *   dashboard reuse, no `/reports` list page reuse, no card-widget
 *   extraction. A future refactor may extract a reusable variant;
 *   this slice keeps the surface tight.
 */

import { Link } from 'react-router-dom'

import { useActorReports } from './useActorReports'

interface ActorLinkedReportsPanelProps {
  actorId: number
}

export function ActorLinkedReportsPanel({
  actorId,
}: ActorLinkedReportsPanelProps): JSX.Element | null {
  const query = useActorReports(actorId)

  // Invalid actor id — the parent should not mount the panel in this
  // case (ActorDetailPage only renders with a valid actor.id), but if
  // it does, render nothing rather than dragging the hook's disabled
  // state through the empty-card branch.
  if (!Number.isInteger(actorId) || actorId <= 0) {
    return null
  }

  if (query.isLoading) {
    return (
      <section
        data-testid="actor-linked-reports-loading"
        role="status"
        aria-busy="true"
        className="h-48 animate-pulse rounded border border-border-card bg-surface"
      />
    )
  }

  if (query.isError) {
    return (
      <section
        data-testid="actor-linked-reports-error"
        role="alert"
        className="flex flex-col items-center justify-center gap-3 rounded border border-border-card bg-surface p-6"
      >
        <h2 className="text-sm font-semibold text-ink">Linked reports</h2>
        <p className="text-sm text-ink-muted">
          Failed to load linked reports for this actor.
        </p>
        <button
          type="button"
          data-testid="actor-linked-reports-retry"
          onClick={() => void query.refetch()}
          className="rounded border border-border-card bg-app px-3 py-1.5 text-xs text-ink hover:border-signal focus:outline-none focus:ring-2 focus:ring-ring"
        >
          Retry
        </button>
      </section>
    )
  }

  const items = query.data?.items ?? []

  // D15 empty contract — distinct state, NOT an error. Renders an
  // honest "no linked reports" card; never injects a fake/heuristic
  // fallback (no "most recent N reports" stand-in, no shared-tag
  // overlap). The distinct testid + positive no-row assertion pins
  // the no-fake-fallback invariant in the test suite.
  if (items.length === 0) {
    return (
      <section
        data-testid="actor-linked-reports-empty"
        data-source-actor-id={actorId}
        aria-labelledby="actor-linked-reports-heading"
        className="rounded border border-border-card bg-surface p-4"
      >
        <h2
          id="actor-linked-reports-heading"
          className="mb-2 text-sm font-semibold text-ink"
        >
          Linked reports
        </h2>
        <p className="text-sm text-ink-muted">
          No reports mention this actor yet.
        </p>
      </section>
    )
  }

  return (
    <section
      data-testid="actor-linked-reports-panel"
      data-source-actor-id={actorId}
      aria-labelledby="actor-linked-reports-heading"
      className="rounded border border-border-card bg-surface p-4"
    >
      <h2
        id="actor-linked-reports-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        Linked reports
      </h2>
      <ul className="divide-y divide-border-card">
        {items.map((item) => (
          <li
            key={item.id}
            data-testid={`actor-linked-reports-item-${item.id}`}
            data-report-id={item.id}
            className="flex flex-col gap-1 px-1 py-2 text-sm"
          >
            <Link
              to={`/reports/${item.id}`}
              className="truncate font-medium text-signal hover:underline"
            >
              {item.title}
            </Link>
            <div className="flex items-center gap-3 text-xs text-ink-muted">
              <span className="font-mono">{item.published}</span>
              <span>·</span>
              <span className="truncate">{item.source_name ?? '—'}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

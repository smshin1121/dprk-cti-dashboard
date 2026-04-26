/**
 * Vertical day-grouped timeline view for /reports.
 *
 * Companion render mode to `ListTable` — same data source
 * (`useReportsList`), different visual posture. Reports are grouped
 * by `published` date with a vertical connector line; each report
 * shows as a node on the line with title link, source, and TLP.
 *
 * Four render states (D11 parity with `ListTable`):
 *  - `loading`    — skeleton: 2 day groups, 3 nodes each, all
 *                   pulsing
 *  - `error`      — inline error card with retry; 429 (rate-limit)
 *                   gets a specific message
 *  - `empty`      — "No reports match the current filters" card
 *  - `populated`  — day groups in BE order (DESC by published);
 *                   reports within each group preserve BE order
 *
 * BE order preservation: BE returns reports DESC by
 * `(published, id)`. We group adjacent same-day rows without
 * re-sorting, so within a day the BE's id-tiebreak holds.
 */

import { AlertTriangle, RotateCcw } from 'lucide-react'

import { ApiError } from '../../lib/api'
import type { ReportItem } from '../../lib/api/schemas'
import { cn } from '../../lib/utils'
import type { ListTableState } from '../lists/ListTable'

export interface ReportTimelineProps {
  rows: readonly ReportItem[]
  state: ListTableState
  error?: unknown
  onRetry?: () => void
}

interface DayGroup {
  day: string
  items: ReportItem[]
}

/** Fold a BE-ordered (DESC by published) list into adjacent
 * same-day groups WITHOUT re-sorting — preserves the BE's
 * id-tiebreak within a day. */
function groupByDay(rows: readonly ReportItem[]): DayGroup[] {
  const groups: DayGroup[] = []
  for (const row of rows) {
    const day = row.published ?? '—'
    const last = groups[groups.length - 1]
    if (last && last.day === day) {
      last.items.push(row)
    } else {
      groups.push({ day, items: [row] })
    }
  }
  return groups
}

export function ReportTimeline({
  rows,
  state,
  error,
  onRetry,
}: ReportTimelineProps): JSX.Element {
  if (state === 'loading') {
    return <TimelineSkeleton />
  }
  if (state === 'error') {
    return <TimelineError error={error} onRetry={onRetry} />
  }
  if (state === 'empty') {
    return (
      <div
        data-testid="reports-timeline-empty"
        className="rounded-md border border-border-card bg-surface p-6 text-center text-sm text-ink-muted"
      >
        No reports match the current filters.
      </div>
    )
  }

  const groups = groupByDay(rows)
  return (
    <ol
      data-testid="reports-timeline"
      data-state="populated"
      className="flex flex-col gap-6"
    >
      {groups.map((group) => (
        <li key={group.day} data-testid={`reports-timeline-day-${group.day}`}>
          <h3 className="mb-2 font-mono text-xs uppercase tracking-wider text-ink-muted">
            {group.day}
          </h3>
          <ol className="flex flex-col gap-3 border-l border-border-card pl-5">
            {group.items.map((row) => (
              <li
                key={row.id}
                data-testid={`reports-timeline-item-${row.id}`}
                className="relative"
              >
                <span
                  aria-hidden="true"
                  className="absolute -left-[23px] top-2 inline-block h-2 w-2 rounded-full bg-signal"
                />
                <a
                  href={row.url}
                  target="_blank"
                  rel="noreferrer"
                  className="block font-medium text-signal hover:underline"
                >
                  {row.title}
                </a>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-ink-muted">
                  <span data-testid={`reports-timeline-source-${row.id}`}>
                    {row.source_name ?? '—'}
                  </span>
                  <span className="font-mono" data-testid={`reports-timeline-tlp-${row.id}`}>
                    {row.tlp ?? '—'}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        </li>
      ))}
    </ol>
  )
}

function TimelineSkeleton(): JSX.Element {
  return (
    <ol
      data-testid="reports-timeline-skeleton"
      aria-busy="true"
      className="flex flex-col gap-6"
    >
      {[0, 1].map((g) => (
        <li key={g}>
          <div className="mb-2 h-3 w-24 animate-pulse rounded bg-surface-elevated" />
          <ol className="flex flex-col gap-3 border-l border-border-card pl-5">
            {[0, 1, 2].map((i) => (
              <li key={i} className="relative">
                <span
                  aria-hidden="true"
                  className="absolute -left-[23px] top-2 inline-block h-2 w-2 rounded-full bg-border-card"
                />
                <div className="h-4 w-3/4 animate-pulse rounded bg-surface-elevated" />
                <div className="mt-1 h-3 w-1/3 animate-pulse rounded bg-surface-elevated" />
              </li>
            ))}
          </ol>
        </li>
      ))}
    </ol>
  )
}

function TimelineError({
  error,
  onRetry,
}: {
  error?: unknown
  onRetry?: () => void
}): JSX.Element {
  const isRateLimit = error instanceof ApiError && error.status === 429
  const message = isRateLimit
    ? 'Too many requests. Wait a moment and try again.'
    : 'Could not load reports. Try again.'
  return (
    <div
      data-testid="reports-timeline-error"
      role="alert"
      className={cn(
        'flex items-center justify-between gap-3 rounded-md border border-border-card bg-surface p-4 text-sm text-ink',
      )}
    >
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-signal" aria-hidden="true" />
        <span>{message}</span>
      </div>
      {onRetry != null && (
        <button
          type="button"
          data-testid="reports-timeline-retry"
          onClick={onRetry}
          className={cn(
            'inline-flex items-center gap-1 rounded border border-border-card bg-surface px-2 py-1 text-xs',
            'hover:border-signal focus:outline-none focus:ring-2 focus:ring-signal',
          )}
        >
          <RotateCcw className="h-3 w-3" aria-hidden="true" />
          Retry
        </button>
      )}
    </div>
  )
}

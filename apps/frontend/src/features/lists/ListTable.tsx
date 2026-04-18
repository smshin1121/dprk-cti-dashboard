/**
 * Shared list-table shell. Four render states (plan D11):
 *
 *  - `loading`    — skeleton rows (aria-busy)
 *  - `error`      — inline error card with retry. 429 (rate-limit)
 *                   gets a specific message; all other errors share
 *                   a generic one.
 *  - `empty`      — "No rows match the current filters" message
 *  - `populated`  — accessible `<table>` with the provided
 *                   column config + a caption for screen readers.
 *
 * Intentionally not a generic grid — no sorting, resizing, or
 * virtualization. Those land when the detail views arrive in
 * PR #13 and the list count grows past "fits on one screen".
 */

import { AlertTriangle, RotateCcw } from 'lucide-react'
import type { ReactNode } from 'react'

import { ApiError } from '../../lib/api'
import { cn } from '../../lib/utils'

export type ListTableState = 'loading' | 'error' | 'empty' | 'populated'

export interface ListTableColumn<T> {
  /** Column heading rendered in the `<th>`. */
  header: string
  /** Extractor for the column's cell content. Receives the row. */
  render: (row: T) => ReactNode
  /** Optional cell className — use to right-align numerics, etc. */
  className?: string
}

export interface ListTableProps<T> {
  caption: string
  columns: readonly ListTableColumn<T>[]
  rows: readonly T[]
  state: ListTableState
  error?: unknown
  onRetry?: () => void
  /** Pull from `row.id` or similar for stable React keys. */
  getRowKey: (row: T) => string | number
}

export function ListTable<T>({
  caption,
  columns,
  rows,
  state,
  error,
  onRetry,
  getRowKey,
}: ListTableProps<T>): JSX.Element {
  if (state === 'loading') {
    return <LoadingBody caption={caption} columns={columns} />
  }
  if (state === 'error') {
    return <ErrorBody caption={caption} error={error} onRetry={onRetry} />
  }
  if (state === 'empty') {
    return <EmptyBody caption={caption} columns={columns} />
  }
  return (
    <div
      data-testid="list-table-populated"
      className="overflow-x-auto rounded-lg border border-border-card bg-surface"
    >
      <table className="w-full text-sm text-ink">
        <caption className="sr-only">{caption}</caption>
        <thead className="border-b border-border-card bg-app text-[10px] font-semibold uppercase tracking-wider text-ink-subtle">
          <tr>
            {columns.map((col) => (
              <th
                key={col.header}
                scope="col"
                className={cn('px-4 py-2 text-left', col.className)}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={getRowKey(row)}
              data-testid="list-table-row"
              className="border-b border-border-card last:border-b-0"
            >
              {columns.map((col) => (
                <td
                  key={col.header}
                  className={cn('px-4 py-2 align-top', col.className)}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface LoadingBodyProps<T> {
  caption: string
  columns: readonly ListTableColumn<T>[]
}

function LoadingBody<T>({ caption, columns }: LoadingBodyProps<T>): JSX.Element {
  return (
    <div
      data-testid="list-table-loading"
      aria-busy="true"
      aria-label={caption}
      className="overflow-hidden rounded-lg border border-border-card bg-surface"
    >
      {/* Skeleton rows — 5 lines, enough to suggest scale but not
          claim a real row count. */}
      <div className="divide-y divide-border-card">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex gap-4 px-4 py-3">
            {columns.map((col) => (
              <div
                key={col.header}
                className="h-3 flex-1 animate-pulse rounded bg-border-card"
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
}

interface ErrorBodyProps {
  caption: string
  error: unknown
  onRetry?: () => void
}

function ErrorBody({ caption, error, onRetry }: ErrorBodyProps): JSX.Element {
  const isRateLimit = error instanceof ApiError && error.status === 429
  return (
    <div
      data-testid="list-table-error"
      role="alert"
      aria-label={caption}
      className="flex flex-col gap-3 rounded-lg border border-border-card bg-surface p-4 text-sm text-ink"
    >
      <div className="flex items-center gap-2 text-destructive">
        <AlertTriangle aria-hidden className="h-4 w-4" />
        {isRateLimit ? (
          <span data-testid="list-table-error-rate-limit">
            Rate limit reached (60/min). Try again in a moment.
          </span>
        ) : (
          <span data-testid="list-table-error-generic">
            Failed to load list.
          </span>
        )}
      </div>
      {onRetry ? (
        <button
          type="button"
          data-testid="list-table-retry"
          onClick={onRetry}
          className={cn(
            'flex items-center gap-1 self-start rounded border border-border-card bg-app px-3 py-1 text-xs text-ink',
            'hover:border-signal focus:outline-none focus:ring-2 focus:ring-signal',
          )}
        >
          <RotateCcw aria-hidden className="h-3 w-3" />
          Retry
        </button>
      ) : null}
    </div>
  )
}

interface EmptyBodyProps<T> {
  caption: string
  columns: readonly ListTableColumn<T>[]
}

function EmptyBody<T>({ caption, columns: _columns }: EmptyBodyProps<T>): JSX.Element {
  return (
    <div
      data-testid="list-table-empty"
      aria-label={caption}
      className="rounded-lg border border-border-card bg-surface p-6 text-center text-sm text-ink-muted"
    >
      No rows match the current filters.
    </div>
  )
}

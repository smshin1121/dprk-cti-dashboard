/**
 * /reports — protected list. Plan §4 Group F.
 *
 * Keyset pagination (plan D3). Consumes the FilterBar's date range
 * only — tag/source/q defer to the advanced filter surface in
 * PR #13. TLP + group are not BE filter params here.
 *
 * Cursor stack:
 * Keeping a stack of previous cursors lets us implement a Previous
 * button without storing BE state. The current page's cursor is the
 * one at the top of the stack; pushing next_cursor advances, popping
 * goes back. Initial load uses no cursor.
 */

import { useState } from 'react'

import { ListTable, type ListTableColumn } from '../features/lists/ListTable'
import { useReportsList } from '../features/reports/useReportsList'
import type { ReportItem } from '../lib/api/schemas'
import { cn } from '../lib/utils'

const PAGE_SIZE = 50

const reportColumns: readonly ListTableColumn<ReportItem>[] = [
  {
    header: 'Published',
    render: (row) => (
      <span className="font-mono text-xs text-ink-muted">{row.published}</span>
    ),
  },
  {
    header: 'Title',
    render: (row) => (
      <a
        href={row.url}
        target="_blank"
        rel="noreferrer"
        className="font-medium text-signal hover:underline"
      >
        {row.title}
      </a>
    ),
  },
  {
    header: 'Source',
    render: (row) => row.source_name ?? '—',
  },
  {
    header: 'TLP',
    render: (row) => row.tlp ?? '—',
    className: 'font-mono text-xs',
  },
] as const

export function ReportsPage(): JSX.Element {
  // Each entry is the cursor used to fetch the corresponding page.
  // `undefined` marks the first page. On Next we push; on Prev we pop.
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([
    undefined,
  ])
  const currentCursor = cursorStack[cursorStack.length - 1]

  const query = useReportsList({ cursor: currentCursor, limit: PAGE_SIZE })

  const state = query.isLoading
    ? 'loading'
    : query.isError
      ? 'error'
      : (query.data?.items.length ?? 0) === 0
        ? 'empty'
        : 'populated'

  const nextCursor = query.data?.next_cursor ?? null
  const hasPrev = cursorStack.length > 1
  const hasNext = nextCursor != null

  return (
    <section
      data-testid="reports-page"
      aria-labelledby="reports-heading"
      className="flex flex-col gap-4 p-6"
    >
      <h1 id="reports-heading" className="text-xl font-semibold">
        Reports
      </h1>

      <ListTable
        caption="Reports list"
        columns={reportColumns}
        rows={query.data?.items ?? []}
        state={state}
        error={query.error}
        onRetry={() => void query.refetch()}
        getRowKey={(row) => row.id}
      />

      <footer
        data-testid="reports-pagination"
        className="flex items-center justify-end gap-2 text-xs text-ink-muted"
      >
        <button
          type="button"
          data-testid="reports-prev"
          disabled={!hasPrev}
          onClick={() =>
            setCursorStack((stack) =>
              stack.length > 1 ? stack.slice(0, -1) : stack,
            )
          }
          className={cn(paginationBtn)}
        >
          Previous
        </button>
        <button
          type="button"
          data-testid="reports-next"
          disabled={!hasNext}
          onClick={() =>
            nextCursor != null
              ? setCursorStack((stack) => [...stack, nextCursor])
              : undefined
          }
          className={cn(paginationBtn)}
        >
          Next
        </button>
      </footer>
    </section>
  )
}

const paginationBtn = cn(
  'rounded border border-border-card bg-surface px-3 py-1 text-ink',
  'hover:border-signal focus:outline-none focus:ring-2 focus:ring-signal',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

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

import { useEffect, useState } from 'react'

import { ReportsViewModeToggle } from '../components/ReportsViewModeToggle'
import { ReportsYearJumpSelect } from '../components/ReportsYearJumpSelect'
import { ListTable, type ListTableColumn } from '../features/lists/ListTable'
import { ReportTimeline } from '../features/reports/ReportTimeline'
import { useReportsList } from '../features/reports/useReportsList'
import type { ReportItem } from '../lib/api/schemas'
import { useReportsViewModeStore } from '../stores/reportsViewMode'
import { useFilterStore } from '../stores/filters'
import { cn } from '../lib/utils'

const PAGE_SIZE = 50

interface CursorState {
  filterKey: string
  stack: (string | undefined)[]
}

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
  const dateFrom = useFilterStore((s) => s.dateFrom)
  const dateTo = useFilterStore((s) => s.dateTo)
  const filterKey = `${dateFrom ?? ''}|${dateTo ?? ''}`
  const [cursorState, setCursorState] = useState<CursorState>({
    filterKey,
    stack: [undefined],
  })

  // Each entry is the cursor used to fetch the corresponding page.
  // `undefined` marks the first page. On Next we push; on Prev we pop.
  // When the date filter changes, the current cursor is stale for the
  // new keyset. Derive first-page state synchronously so no request is
  // issued with a new date range and an old opaque cursor.
  const cursorStack =
    cursorState.filterKey === filterKey ? cursorState.stack : [undefined]
  const currentCursor = cursorStack[cursorStack.length - 1]

  useEffect(() => {
    setCursorState((state) =>
      state.filterKey === filterKey
        ? state
        : { filterKey, stack: [undefined] },
    )
  }, [filterKey])

  const query = useReportsList({ cursor: currentCursor, limit: PAGE_SIZE })
  const viewMode = useReportsViewModeStore((s) => s.mode)

  const state = query.isLoading
    ? 'loading'
    : query.isError
      ? 'error'
      : (query.data?.items.length ?? 0) === 0
        ? 'empty'
        : 'populated'

  const rows = query.data?.items ?? []
  const nextCursor = query.data?.next_cursor ?? null
  const hasPrev = cursorStack.length > 1
  const hasNext = nextCursor != null

  return (
    <section
      data-testid="reports-page"
      aria-labelledby="reports-heading"
      className="flex flex-col gap-4 p-6"
    >
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 id="reports-heading" className="text-xl font-semibold">
          Reports
        </h1>
        <div className="flex items-center gap-3">
          <ReportsYearJumpSelect />
          <ReportsViewModeToggle />
        </div>
      </header>

      {viewMode === 'list' ? (
        <ListTable
          caption="Reports list"
          columns={reportColumns}
          rows={rows}
          state={state}
          error={query.error}
          onRetry={() => void query.refetch()}
          getRowKey={(row) => row.id}
        />
      ) : (
        <ReportTimeline
          rows={rows}
          state={state}
          error={query.error}
          onRetry={() => void query.refetch()}
        />
      )}

      <footer
        data-testid="reports-pagination"
        className="flex items-center justify-end gap-2 text-xs text-ink-muted"
      >
        <button
          type="button"
          data-testid="reports-prev"
          disabled={!hasPrev}
          onClick={() =>
            setCursorState((state) =>
              state.filterKey !== filterKey
                ? { filterKey, stack: [undefined] }
                : {
                    filterKey,
                    stack:
                      state.stack.length > 1
                        ? state.stack.slice(0, -1)
                        : state.stack,
                  },
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
              ? setCursorState((state) => ({
                  filterKey,
                  stack:
                    state.filterKey === filterKey
                      ? [...state.stack, nextCursor]
                      : [undefined, nextCursor],
                }))
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
  'hover:border-signal focus:outline-none focus:ring-2 focus:ring-ring',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

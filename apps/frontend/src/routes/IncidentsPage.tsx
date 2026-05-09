/**
 * /incidents — protected list. Plan §4 Group F.
 *
 * Keyset pagination (plan D3). Consumes the FilterBar's date range
 * only — motivation/sector/country filter surfaces defer to PR #13.
 *
 * See `ReportsPage.tsx` for cursor-stack rationale (shared pattern).
 */

import { useState } from 'react'

import { ListTable, type ListTableColumn } from '../features/lists/ListTable'
import { useIncidentsList } from '../features/incidents/useIncidentsList'
import type { IncidentItem } from '../lib/api/schemas'
import { cn } from '../lib/utils'

const PAGE_SIZE = 50

function formatLossUsd(value: number | null | undefined): string {
  if (value == null) return '—'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value)
}

const incidentColumns: readonly ListTableColumn<IncidentItem>[] = [
  {
    header: 'Reported',
    render: (row) => (
      <span className="font-mono text-xs text-ink-muted">
        {row.reported ?? '—'}
      </span>
    ),
  },
  {
    header: 'Title',
    render: (row) => <span className="font-medium text-ink">{row.title}</span>,
  },
  {
    header: 'Motivation',
    render: (row) => (row.motivations.length > 0 ? row.motivations.join(', ') : '—'),
  },
  {
    header: 'Countries',
    render: (row) => (row.countries.length > 0 ? row.countries.join(', ') : '—'),
  },
  {
    header: 'Est. loss',
    render: (row) => (
      <span className="font-mono text-xs">{formatLossUsd(row.est_loss_usd)}</span>
    ),
    className: 'text-right',
  },
] as const

export function IncidentsPage(): JSX.Element {
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([
    undefined,
  ])
  const currentCursor = cursorStack[cursorStack.length - 1]

  const query = useIncidentsList({ cursor: currentCursor, limit: PAGE_SIZE })

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
      data-testid="incidents-page"
      data-page-class="analyst-workspace"
      aria-labelledby="incidents-heading"
      className="flex flex-col gap-4 p-6"
    >
      <h1
        id="incidents-heading"
        className="text-2xl font-display tracking-display"
      >
        Incidents
      </h1>

      <ListTable
        caption="Incidents list"
        columns={incidentColumns}
        rows={query.data?.items ?? []}
        state={state}
        error={query.error}
        onRetry={() => void query.refetch()}
        getRowKey={(row) => row.id}
      />

      <footer
        data-testid="incidents-pagination"
        className="flex items-center justify-end gap-2 text-xs text-ink-muted"
      >
        <button
          type="button"
          data-testid="incidents-prev"
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
          data-testid="incidents-next"
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
  'rounded-none border border-border-card bg-surface px-3 py-1 text-xs font-cta uppercase tracking-cta text-ink',
  'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

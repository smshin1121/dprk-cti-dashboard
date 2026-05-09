/**
 * /actors — protected list. Plan §4 Group F.
 *
 * Offset pagination (plan D3). The BE endpoint has no filter
 * contract, so the FilterBar's date/group/TLP selections are
 * intentionally not consumed here — see `useActorsList.ts`.
 */

import { useState } from 'react'

import { ListTable, type ListTableColumn } from '../features/lists/ListTable'
import { useActorsList } from '../features/actors/useActorsList'
import type { ActorItem } from '../lib/api/schemas'
import { cn } from '../lib/utils'

const PAGE_SIZE = 50

const actorColumns: readonly ListTableColumn<ActorItem>[] = [
  {
    header: 'Name',
    render: (row) => (
      <span className="font-medium text-ink">{row.name}</span>
    ),
  },
  {
    header: 'MITRE ID',
    render: (row) => (
      <span className="font-mono text-xs text-ink-muted">
        {row.mitre_intrusion_set_id ?? '—'}
      </span>
    ),
  },
  {
    header: 'Aliases',
    render: (row) => (row.aka.length > 0 ? row.aka.join(', ') : '—'),
  },
  {
    header: 'Codenames',
    render: (row) =>
      row.codenames.length > 0 ? row.codenames.join(', ') : '—',
  },
] as const

export function ActorsPage(): JSX.Element {
  const [offset, setOffset] = useState(0)
  const query = useActorsList({ limit: PAGE_SIZE, offset })

  const state = query.isLoading
    ? 'loading'
    : query.isError
      ? 'error'
      : (query.data?.items.length ?? 0) === 0
        ? 'empty'
        : 'populated'

  const total = query.data?.total ?? 0
  const hasPrev = offset > 0
  const hasNext = offset + PAGE_SIZE < total

  return (
    <section
      data-testid="actors-page"
      data-page-class="analyst-workspace"
      aria-labelledby="actors-heading"
      className="flex flex-col gap-4 p-6"
    >
      <h1
        id="actors-heading"
        className="text-2xl font-display tracking-display"
      >
        Actors
      </h1>

      <ListTable
        caption="Threat actors list"
        columns={actorColumns}
        rows={query.data?.items ?? []}
        state={state}
        error={query.error}
        onRetry={() => void query.refetch()}
        getRowKey={(row) => row.id}
      />

      <footer
        data-testid="actors-pagination"
        className="flex items-center justify-between text-xs text-ink-muted"
      >
        <span>
          {total > 0
            ? `Showing ${offset + 1}–${Math.min(offset + PAGE_SIZE, total)} of ${total}`
            : ''}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            data-testid="actors-prev"
            disabled={!hasPrev}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            className={cn(paginationBtn)}
          >
            Previous
          </button>
          <button
            type="button"
            data-testid="actors-next"
            disabled={!hasNext}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            className={cn(paginationBtn)}
          >
            Next
          </button>
        </div>
      </footer>
    </section>
  )
}

const paginationBtn = cn(
  'rounded-none border border-border-card bg-surface px-3 py-1 text-xs font-cta uppercase tracking-cta text-ink',
  'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

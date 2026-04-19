/**
 * `/actors/:id` — protected actor detail view.
 *
 * History:
 *   - PR #14 Group E: original mount (plan D1 + D11, no reports).
 *   - PR #15 Group E: adds the `ActorLinkedReportsPanel` below the
 *     codenames section. The panel comes from a SIBLING endpoint
 *     (`GET /api/v1/actors/{id}/reports`, new in PR #15), NOT from
 *     enriching the `ActorDetail` payload.
 *
 * D12 invariant (preserved):
 *   `actorDetailSchema` shape is UNCHANGED. The detail fetch still
 *   returns `{id, name, mitre_intrusion_set_id, aka, description,
 *   codenames}` only — any BE leak of reports-like keys is stripped
 *   at the Zod parse boundary. The new panel below renders reports
 *   from a DIFFERENT fetch, so the two-surface architecture is
 *   visible at both the render tree and the network tab.
 *
 * D18 scope:
 *   `ActorLinkedReportsPanel` mounts INSIDE the populated branch
 *   (after detail success). Loading / error / 404 branches do not
 *   mount the panel — the page renders a single state at a time to
 *   keep the reader's attention focused.
 */

import { useParams } from 'react-router-dom'

import { ActorLinkedReportsPanel } from '../features/actor/ActorLinkedReportsPanel'
import { useActorDetail } from '../features/detail/useActorDetail'
import { ApiError } from '../lib/api'
import { parseDetailId } from './detailParams'
import { ErrorPanel, NotFoundPanel } from './ReportDetailPage'

export function ActorDetailPage(): JSX.Element {
  const { id: idParam } = useParams<{ id: string }>()
  const id = parseDetailId(idParam)
  const query = useActorDetail(id ?? 0)

  if (id == null) {
    return <NotFoundPanel testId="actor-detail-notfound" kind="actor" />
  }

  if (query.isLoading) {
    return (
      <section
        data-testid="actor-detail-loading"
        role="status"
        aria-busy="true"
        className="m-6 h-64 animate-pulse rounded-lg border border-border-card bg-surface"
      />
    )
  }

  if (query.isError) {
    if (query.error instanceof ApiError && query.error.status === 404) {
      return <NotFoundPanel testId="actor-detail-notfound" kind="actor" />
    }
    return (
      <ErrorPanel
        testId="actor-detail-error"
        onRetry={() => void query.refetch()}
      />
    )
  }

  const actor = query.data!
  return (
    <section
      data-testid="actor-detail-page"
      data-actor-id={actor.id}
      aria-labelledby="actor-detail-heading"
      className="flex flex-col gap-6 p-6"
    >
      <header className="flex flex-col gap-2">
        <h1
          id="actor-detail-heading"
          className="text-xl font-semibold text-ink"
        >
          {actor.name}
        </h1>
        {actor.mitre_intrusion_set_id != null && (
          <span className="font-mono text-xs text-ink-muted">
            {actor.mitre_intrusion_set_id}
          </span>
        )}
      </header>

      {actor.description != null && (
        <p
          data-testid="actor-detail-description"
          className="text-sm text-ink"
        >
          {actor.description}
        </p>
      )}

      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
        {actor.aka.length > 0 && (
          <DLEntry label="Aliases" value={actor.aka.join(', ')} />
        )}
        {actor.codenames.length > 0 && (
          <DLEntry label="Codenames" value={actor.codenames.join(', ')} />
        )}
      </dl>

      <ActorLinkedReportsPanel actorId={actor.id} />
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

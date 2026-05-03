/**
 * Top-groups mini list — design doc §4.2 area [E] secondary panel.
 * Plan D1 + D9 (PR #13 Group I).
 *
 * Data: `useDashboardSummary()` — SAME hook KPIStrip / MotivationDonut
 * / YearBar consume. React Query's cache key is shared across every
 * subscriber under the same filter set, so mounting this panel
 * alongside the rest of the strip fires ONE `/dashboard/summary`
 * request for the page. The `summarySharedCache.test.tsx` invariant
 * is extended to mount this component too — a future refactor that
 * adds a bespoke `/analytics/top_groups` hook would flip that test
 * red immediately.
 *
 * Rationale for reusing the dashboard summary:
 *   The BE already returns `top_groups` inside `/dashboard/summary`
 *   (plan D6 aggregator). Adding a separate `/analytics/top_groups`
 *   endpoint would duplicate the path for zero gain — filter
 *   contract is identical and the payload already ships with the
 *   strip. Plan D9 locks per-viz query separation at the analytics
 *   endpoints (attack_matrix / trend / geo); the mini-list + donut +
 *   year bar stay on the summary scope because their data is a
 *   literal slice of that response.
 *
 * Four render states (review invariant per user):
 *   - loading    → skeleton
 *   - error      → inline error card + retry
 *   - empty      → dedicated empty card (top_groups length === 0)
 *   - populated  → ordered list with per-row count badge
 *
 * BE ordering:
 *   `top_groups` arrives sorted by `report_count` desc (see
 *   `dashboard_aggregator.py`). We preserve that order in the list
 *   rather than re-sorting client-side.
 */

import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { cn } from '../../lib/utils'
import { useDashboardSummary } from './useDashboardSummary'

export function GroupsMiniList(): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useDashboardSummary()

  if (isLoading) {
    return (
      <div
        data-testid="groups-mini-list-loading"
        role="status"
        aria-busy="true"
        className="h-64 animate-pulse rounded border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid="groups-mini-list-error"
        role="alert"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid="groups-mini-list-retry"
          onClick={() => void refetch()}
          className={cn(
            'rounded border border-border-card bg-app px-3 py-1.5 text-xs text-ink',
            'hover:border-signal focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          {t('list.retry')}
        </button>
      </div>
    )
  }

  const groups = data?.top_groups ?? []

  if (groups.length === 0) {
    return (
      <section
        data-testid="groups-mini-list-empty"
        className="flex h-64 flex-col items-center justify-center gap-2 rounded border border-border-card bg-surface p-6"
      >
        <h3 className="text-sm font-semibold text-ink">
          {t('dashboard.groupsMiniList.title')}
        </h3>
        <p className="text-sm text-ink-muted">
          {t('dashboard.groupsMiniList.empty')}
        </p>
      </section>
    )
  }

  return (
    <section
      data-testid="groups-mini-list"
      aria-labelledby="groups-mini-list-heading"
      className="rounded border border-border-card bg-surface p-4"
    >
      <h3
        id="groups-mini-list-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t('dashboard.groupsMiniList.title')}
      </h3>
      <ol data-testid="groups-mini-list-items" className="divide-y divide-border-card">
        {groups.map((group) => (
          <li
            key={group.group_id}
            data-testid={`groups-mini-list-item-${group.group_id}`}
            data-group-id={group.group_id}
            data-report-count={group.report_count}
            className="px-1 py-2 text-sm"
          >
            {/* PR #14 D11: row navigates to `/actors/:id` — the
                `top_groups` payload carries `group_id` which aligns
                with the actor PK (groups are actor rows in this
                schema; see `actors_table` migration 0001). */}
            <Link
              to={`/actors/${group.group_id}`}
              className="flex items-center justify-between gap-3 rounded hover:text-signal focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <span className="truncate font-medium text-ink">{group.name}</span>
              <span className="shrink-0 rounded bg-app px-2 py-0.5 text-xs font-mono text-ink-muted">
                {group.report_count}{' '}
                <span className="text-ink-subtle">
                  {t('dashboard.groupsMiniList.reportsSuffix')}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  )
}

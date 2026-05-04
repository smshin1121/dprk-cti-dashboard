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

import { RankedRowWithShareBar } from '../../layout/RankedRowWithShareBar'
import { cn } from '../../lib/utils'
import { useDashboardSummary } from './useDashboardSummary'

function groupAvatarInitials(name: string): string {
  // Two-char initials from a group name. Falls back to first 2 chars
  // when the name has only one word (e.g. "Lazarus" → "LA").
  const parts = name.trim().split(/\s+/)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }
  return name.slice(0, 2).toUpperCase()
}

export function GroupsMiniList(): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useDashboardSummary()

  if (isLoading) {
    return (
      <div
        data-testid="groups-mini-list-loading"
        role="status"
        aria-busy="true"
        className="h-64 animate-pulse rounded-none border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid="groups-mini-list-error"
        role="alert"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded-none border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid="groups-mini-list-retry"
          onClick={() => void refetch()}
          className={cn(
            'rounded-none border border-border-card bg-app px-3 py-1.5 text-xs font-cta uppercase tracking-cta text-ink',
            'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          {t('list.retry')}
        </button>
      </div>
    )
  }

  const groups = data?.top_groups ?? []
  // Head row's report_count is the max (BE sorts top_groups by
  // report_count DESC); coerce to 1 if the head somehow holds 0
  // to avoid divide-by-zero.
  const maxReportCount =
    groups.length > 0 ? Math.max(groups[0].report_count, 1) : 1

  if (groups.length === 0) {
    return (
      <section
        data-testid="groups-mini-list-empty"
        className="flex h-64 flex-col items-center justify-center gap-2 rounded-none border border-border-card bg-surface p-6"
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
      className="rounded-none border border-border-card bg-surface p-4"
    >
      <h3
        id="groups-mini-list-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t('dashboard.groupsMiniList.title')}
      </h3>
      <ol data-testid="groups-mini-list-items" className="flex flex-col">
        {groups.map((group) => {
          const ratio = (group.report_count / maxReportCount) * 100
          return (
            <li
              key={group.group_id}
              data-testid={`groups-mini-list-item-${group.group_id}`}
              data-group-id={group.group_id}
              data-report-count={group.report_count}
            >
              {/* PR #14 D11: row navigates to `/actors/:id` — the
                  `top_groups` payload carries `group_id` which aligns
                  with the actor PK. */}
              <Link
                to={`/actors/${group.group_id}`}
                className="block focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <RankedRowWithShareBar
                  avatarText={groupAvatarInitials(group.name)}
                  name={group.name}
                  value={`${group.report_count} ${t('dashboard.groupsMiniList.reportsSuffix')}`}
                  shareBarPct={ratio}
                  barFillTestId={`groups-mini-list-bar-${group.group_id}`}
                />
              </Link>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

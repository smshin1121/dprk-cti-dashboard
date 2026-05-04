/**
 * SectorBreakdown — top-N target sectors as a ranked horizontal bar
 * list. PR #23 §6.C C9, lazarus.day parity for the "Sectors ranked"
 * widget.
 *
 * Data: `useDashboardSummary().top_sectors`. Same hook + cache slot as
 * KPIStrip / MotivationDonut / YearBar / GroupsMiniList — adding this
 * panel does NOT trigger an extra `/dashboard/summary` request. The
 * `summarySharedCache.test.tsx` invariant covers this on the existing
 * widget set; this widget joins the same cache subscriber group.
 *
 * Rationale for reusing the dashboard summary scope (same as
 * MotivationDonut / GroupsMiniList): the BE already returns
 * `top_sectors` inside `/dashboard/summary` as of PR #23 §6.A C2.
 * Adding a separate `/analytics/sectors` endpoint would duplicate
 * the path for zero gain.
 *
 * Visual:
 * Pure CSS bars (width = count / max_count * 100%) — no Recharts.
 * Lightweight, no ResizeObserver concerns under happy-dom, and the
 * bar list reads like a leaderboard which is what the lazarus.day
 * "Target Sectors" widget conveys.
 *
 * Four render states (TrendChart / GroupsMiniList parity).
 */

import { useTranslation } from 'react-i18next'

import { RankedRowWithShareBar } from '../../layout/RankedRowWithShareBar'
import { cn } from '../../lib/utils'
import { useDashboardSummary } from './useDashboardSummary'

export function SectorBreakdown(): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useDashboardSummary()

  if (isLoading) {
    return (
      <div
        data-testid="sector-breakdown-loading"
        role="status"
        aria-busy="true"
        className="h-64 animate-pulse rounded-none border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid="sector-breakdown-error"
        role="alert"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded-none border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid="sector-breakdown-retry"
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

  const sectors = data?.top_sectors ?? []

  if (sectors.length === 0) {
    return (
      <section
        data-testid="sector-breakdown-empty"
        className="flex h-64 flex-col items-center justify-center gap-2 rounded-none border border-border-card bg-surface p-6"
      >
        <h3 className="text-sm font-semibold text-ink">
          {t('dashboard.sectorBreakdown.title')}
        </h3>
        <p className="text-sm text-ink-muted">
          {t('dashboard.sectorBreakdown.empty')}
        </p>
      </section>
    )
  }

  // BE arrives sorted count DESC (see dashboard_aggregator.py PR #23
  // §6.A C2). Max is therefore the head row's count — no Math.max
  // pass needed, but defensively coerce when the head somehow holds 0
  // (would only happen if the BE invariant breaks).
  const maxCount = Math.max(sectors[0].count, 1)

  return (
    <section
      data-testid="sector-breakdown"
      aria-labelledby="sector-breakdown-heading"
      className="rounded-none border border-border-card bg-surface p-4"
    >
      <h3
        id="sector-breakdown-heading"
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t('dashboard.sectorBreakdown.title')}
      </h3>
      <ol data-testid="sector-breakdown-items" className="flex flex-col">
        {sectors.map((sector) => {
          const ratio = (sector.count / maxCount) * 100
          return (
            <li
              key={sector.sector_code}
              data-testid={`sector-breakdown-item-${sector.sector_code}`}
              data-sector-code={sector.sector_code}
              data-count={sector.count}
            >
              <RankedRowWithShareBar
                avatarText={sector.sector_code}
                name={sector.sector_code}
                value={String(sector.count)}
                shareBarPct={ratio}
                barFillTestId={`sector-breakdown-bar-${sector.sector_code}`}
              />
            </li>
          )
        })}
      </ol>
    </section>
  )
}

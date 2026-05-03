/**
 * ATT&CK tactic × technique matrix — design doc §4.2 area [D]
 * primary viz. Plan D1 + D8 (PR #13 Group H).
 *
 * Data: `useAttackMatrix({ top_n })` (Group C). BE returns the
 * row-based shape locked in plan D2:
 *
 *     { tactics: TacticRef[], rows: [{tactic_id, techniques: [...]}] }
 *
 * This component consumes that shape VERBATIM — no re-pivot to a
 * sparse-cells list, no flattening to (tactic, technique) pairs on
 * the client, no derived dictionaries. The aggregator's output is
 * the viz's input.
 *
 * top_n contract (plan D8):
 *   Default `DEFAULT_TOP_N = 30`. User toggle expands to
 *   `EXPANDED_TOP_N = 200` (matching the BE router's `Query(le=200)`
 *   upper bound). The pair is a CONTRACT: default is the entry
 *   point users land on; expanding is explicit. If we ever want to
 *   change the default, it lands here (single constant) and flows
 *   through the queryKey — a test pins the current value so a
 *   silent bump fires a red check.
 *
 * Empty-matrix UX (plan D8 lock):
 *   Dedicated empty-state card ("No ATT&CK activity for current
 *   filters" + clear-filters CTA). NOT a collapsed heatmap overlay.
 *   Rationale in plan D8: collapsed overlays wobble layout and are
 *   weak explanations; empty card has clear copy + recovery action.
 *
 * Grid rendering:
 *   Plain HTML/CSS (not a chart library) — the matrix is a set of
 *   tactic rows, each with its own set of technique cells. A
 *   regular `@visx/heatmap` assumes a dense x×y grid where every
 *   cell has a value; our rows have variable technique counts.
 *   CSS grid gives us a readable layout without the fight.
 */

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useAttackMatrix } from '../analytics/useAttackMatrix'
import { cn } from '../../lib/utils'
import { useFilterStore } from '../../stores/filters'

export const DEFAULT_TOP_N = 30
export const EXPANDED_TOP_N = 200

// Sequential ramp from canvas-elevated (low count) to Rosso Corsa
// (high count). The ramp is the one place the heatmap uses Rosso
// Corsa — it signals "highest tactic activity" which qualifies as a
// priority highlight per plan §0.1 invariant 3 + DESIGN.md §Don'ts
// (Rosso Corsa scarce; CTI domain mapping to "race-position
// highlights").
const CELL_FILL_NO_DATA = '#3a3a3a' // canvas-elevated +slight lift
const CELL_FILL_HIGH = '#da291c' // Rosso Corsa (top intensity)

function cellFill(count: number, maxCount: number): string {
  if (maxCount <= 0 || count <= 0) return CELL_FILL_NO_DATA
  const t = Math.min(1, count / maxCount)
  // Linear interpolation in sRGB between #3a3a3a (no-data) and
  // #da291c (Rosso Corsa). Good-enough perceptual ramp for a
  // qualitative heatmap — no need for OKLCH at this density.
  const r = Math.round(0x3a + (0xda - 0x3a) * t)
  const g = Math.round(0x3a + (0x29 - 0x3a) * t)
  const b = Math.round(0x3a + (0x1c - 0x3a) * t)
  return `rgb(${r} ${g} ${b})`
}

function Skeleton(): JSX.Element {
  return (
    <div
      data-testid="attack-heatmap-loading"
      role="status"
      aria-busy="true"
      className="h-64 animate-pulse rounded-none border border-border-card bg-surface"
    />
  )
}

interface ErrorCardProps {
  onRetry: () => void
  errorLabel: string
  retryLabel: string
}

function ErrorCard({ onRetry, errorLabel, retryLabel }: ErrorCardProps): JSX.Element {
  return (
    <div
      data-testid="attack-heatmap-error"
      role="alert"
      className="flex h-64 flex-col items-center justify-center gap-3 rounded-none border border-border-card bg-surface p-6"
    >
      <p className="text-sm text-ink-muted">{errorLabel}</p>
      <button
        type="button"
        data-testid="attack-heatmap-retry"
        onClick={onRetry}
        className={cn(
          'rounded-none border border-border-card bg-app px-3 py-1.5 text-xs font-cta uppercase tracking-cta text-ink',
          'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
        )}
      >
        {retryLabel}
      </button>
    </div>
  )
}

export function AttackHeatmap(): JSX.Element {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const topN = expanded ? EXPANDED_TOP_N : DEFAULT_TOP_N
  const clearFilters = useFilterStore((s) => s.clear)

  const { data, isLoading, isError, refetch } = useAttackMatrix({ top_n: topN })

  const maxCount = useMemo(() => {
    if (!data || data.rows.length === 0) return 0
    let max = 0
    for (const row of data.rows) {
      for (const tech of row.techniques) {
        if (tech.count > max) max = tech.count
      }
    }
    return max
  }, [data])

  if (isLoading) return <Skeleton />

  if (isError) {
    return (
      <ErrorCard
        onRetry={() => void refetch()}
        errorLabel={t('dashboard.error')}
        retryLabel={t('list.retry')}
      />
    )
  }

  const isEmpty = !data || data.rows.length === 0

  if (isEmpty) {
    // Plan D8 lock: dedicated empty-state card + clear-filters CTA.
    // NOT a collapsed overlay over the heatmap — the heatmap is
    // literally absent when there's nothing to show.
    return (
      <section
        data-testid="attack-heatmap-empty"
        aria-labelledby="attack-heatmap-empty-heading"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded-none border border-border-card bg-surface p-6"
      >
        <h3
          id="attack-heatmap-empty-heading"
          className="text-sm font-semibold text-ink"
        >
          {t('dashboard.attackHeatmap.title')}
        </h3>
        <p className="text-sm text-ink-muted">
          {t('dashboard.attackHeatmap.empty')}
        </p>
        <button
          type="button"
          data-testid="attack-heatmap-empty-clear-filters"
          onClick={clearFilters}
          className={cn(
            'rounded-none border border-border-card bg-app px-3 py-1.5 text-xs font-cta uppercase tracking-cta text-ink',
            'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          {t('dashboard.attackHeatmap.clearFilters')}
        </button>
      </section>
    )
  }

  return (
    <section
      data-testid="attack-heatmap"
      aria-labelledby="attack-heatmap-heading"
      data-top-n={topN}
      className="rounded-none border border-border-card bg-surface p-4"
    >
      <header className="mb-3 flex items-center justify-between">
        <h3
          id="attack-heatmap-heading"
          className="text-sm font-semibold text-ink"
        >
          {t('dashboard.attackHeatmap.title')}
        </h3>
        <button
          type="button"
          data-testid="attack-heatmap-toggle"
          onClick={() => setExpanded((e) => !e)}
          className={cn(
            'rounded-none border border-border-card bg-app px-2 py-1 text-[10px] font-cta uppercase tracking-cta text-ink-muted',
            'hover:border-border-strong hover:text-ink focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          {expanded
            ? t('dashboard.attackHeatmap.showTopN', { n: DEFAULT_TOP_N })
            : t('dashboard.attackHeatmap.showAll')}
        </button>
      </header>

      <div role="table" data-testid="attack-heatmap-grid" className="space-y-1">
        {data.rows.map((row) => (
          <div
            key={row.tactic_id}
            role="row"
            data-testid={`attack-heatmap-row-${row.tactic_id}`}
            className="flex items-stretch gap-2"
          >
            <div
              role="rowheader"
              className="w-24 shrink-0 rounded-none bg-app px-2 py-1.5 text-[11px] font-cta uppercase tracking-caption text-ink"
            >
              {row.tactic_id}
            </div>
            <div role="cell" className="flex flex-1 flex-wrap gap-1">
              {row.techniques.map((tech) => (
                <div
                  key={tech.technique_id}
                  data-testid={`attack-heatmap-cell-${row.tactic_id}-${tech.technique_id}`}
                  data-technique-id={tech.technique_id}
                  data-count={tech.count}
                  title={`${tech.technique_id}: ${tech.count}`}
                  className="flex min-w-[68px] items-center justify-between rounded-none border border-border-card px-2 py-1 text-[11px]"
                  style={{ backgroundColor: cellFill(tech.count, maxCount) }}
                >
                  <span className="font-mono text-ink">{tech.technique_id}</span>
                  <span className="ml-2 font-semibold text-ink">{tech.count}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

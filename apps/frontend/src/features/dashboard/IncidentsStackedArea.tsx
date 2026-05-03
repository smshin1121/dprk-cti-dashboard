/**
 * Stacked-area widgets for the incidents-trend axis — PR #23 §6.C
 * C7 (motivation) + C8 (sector). Both wrap a single internal helper
 * that pivots the BE response (long format: month + series rows) into
 * Recharts wide format (one row per month with one column per axis
 * key) and stacks the areas by stackId.
 *
 * Color palette is the PR #24 chart-theme placeholder — sequential
 * HSL hues. The PR #24 visual redesign will replace this with the
 * Paul Tol palette (locked in plan §2.2). Until then the placeholder
 * keeps the widget visually distinct without committing to a final
 * brand identity.
 *
 * Four render states (TrendChart parity):
 *   - loading    → skeleton
 *   - error      → inline error card + retry button
 *   - empty      → buckets.length === 0 dedicated empty card
 *   - populated  → AreaChart at fixed dimensions (no
 *                  ResponsiveContainer; happy-dom + ResizeObserver
 *                  is the known trap)
 *
 * The "unknown" slice (BE constant `INCIDENTS_TREND_UNKNOWN_KEY`)
 * surfaces here as a regular axis row but with an i18n-translated
 * label so the FE shows "Unassigned" / "미분류" instead of the raw
 * sentinel string.
 */

import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { useIncidentsTrend } from '../analytics/useIncidentsTrend'
import { INCIDENTS_TREND_UNKNOWN_KEY } from '../../lib/api/schemas'
import { cn } from '../../lib/utils'
import type { IncidentsTrendGroupBy } from '../../lib/analyticsFilters'

const CHART_WIDTH = 480
const CHART_HEIGHT = 260

interface PivotedRow {
  month: string
  [axisKey: string]: number | string
}

interface PaletteEntry {
  key: string
  displayLabel: string
  color: string
}

const PALETTE_HUES = [205, 28, 145, 268, 5, 50, 180, 320, 95, 240]

function paletteColor(index: number): string {
  const hue = PALETTE_HUES[index % PALETTE_HUES.length]
  return `hsl(${hue} 65% 50%)`
}

/**
 * Pivot the BE long-form response into Recharts wide-form rows AND
 * compute the unique-key palette. Single pass over buckets keeps this
 * O(B + S·B) where S is the number of unique series keys (at most
 * the cardinality of motivation or sector — small).
 */
function pivotToWideFormat(
  buckets: ReadonlyArray<{
    month: string
    count: number
    series: ReadonlyArray<{ key: string; count: number }>
  }>,
  unknownLabel: string,
): { rows: PivotedRow[]; palette: PaletteEntry[] } {
  const allKeys = new Set<string>()
  for (const bucket of buckets) {
    for (const item of bucket.series) {
      allKeys.add(item.key)
    }
  }

  // Sort with the unknown sentinel pinned FIRST so it renders as the
  // first <Area> child of <AreaChart>. In a Recharts stack the first
  // sibling sits at the visual BOTTOM of the stack (closest to the X
  // axis); subsequent siblings stack on top. Putting unknown first
  // grounds it as the "tail" slice at the bottom, consistently across
  // both axes.
  const orderedKeys = Array.from(allKeys).sort((a, b) => {
    if (a === INCIDENTS_TREND_UNKNOWN_KEY) return -1
    if (b === INCIDENTS_TREND_UNKNOWN_KEY) return 1
    return a.localeCompare(b)
  })

  const palette: PaletteEntry[] = orderedKeys.map((key, index) => ({
    key,
    displayLabel: key === INCIDENTS_TREND_UNKNOWN_KEY ? unknownLabel : key,
    color: paletteColor(index),
  }))

  const rows: PivotedRow[] = buckets.map((bucket) => {
    const row: PivotedRow = { month: bucket.month }
    for (const key of orderedKeys) row[key] = 0
    for (const item of bucket.series) row[item.key] = item.count
    return row
  })

  return { rows, palette }
}

interface IncidentsStackedAreaProps {
  axis: IncidentsTrendGroupBy
  /** i18n namespace key — `dashboard.motivationStackedArea` or
   *  `dashboard.sectorStackedArea`. The widget reads `.title`,
   *  `.empty`, and `.unknownLabel` from this namespace. */
  i18nNamespace: string
  /** Stable testid prefix; the four state-specific ids derive from
   *  it so the test suite can target the same widget across states
   *  without clashing with the sister widget. */
  testIdPrefix: string
}

function IncidentsStackedArea({
  axis,
  i18nNamespace,
  testIdPrefix,
}: IncidentsStackedAreaProps): JSX.Element {
  const { t } = useTranslation()
  const { data, isLoading, isError, refetch } = useIncidentsTrend({
    groupBy: axis,
  })

  const unknownLabel = t(`${i18nNamespace}.unknownLabel`)

  const { rows, palette } = useMemo(() => {
    if (!data) return { rows: [], palette: [] as PaletteEntry[] }
    return pivotToWideFormat(data.buckets, unknownLabel)
  }, [data, unknownLabel])

  if (isLoading) {
    return (
      <div
        data-testid={`${testIdPrefix}-loading`}
        role="status"
        aria-busy="true"
        className="h-64 animate-pulse rounded border border-border-card bg-surface"
      />
    )
  }

  if (isError) {
    return (
      <div
        data-testid={`${testIdPrefix}-error`}
        role="alert"
        className="flex h-64 flex-col items-center justify-center gap-3 rounded border border-border-card bg-surface p-6"
      >
        <p className="text-sm text-ink-muted">{t('dashboard.error')}</p>
        <button
          type="button"
          data-testid={`${testIdPrefix}-retry`}
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

  if (rows.length === 0) {
    return (
      <section
        data-testid={`${testIdPrefix}-empty`}
        className="flex h-64 flex-col items-center justify-center gap-2 rounded border border-border-card bg-surface p-6"
      >
        <h3 className="text-sm font-semibold text-ink">
          {t(`${i18nNamespace}.title`)}
        </h3>
        <p className="text-sm text-ink-muted">
          {t(`${i18nNamespace}.empty`)}
        </p>
      </section>
    )
  }

  return (
    <section
      data-testid={testIdPrefix}
      aria-labelledby={`${testIdPrefix}-heading`}
      className="rounded border border-border-card bg-surface p-4"
    >
      <h3
        id={`${testIdPrefix}-heading`}
        className="mb-3 text-sm font-semibold text-ink"
      >
        {t(`${i18nNamespace}.title`)}
      </h3>
      <AreaChart
        width={CHART_WIDTH}
        height={CHART_HEIGHT}
        data={rows}
        margin={{ top: 8, right: 16, bottom: 20, left: 0 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(210 10% 85%)" />
        <XAxis
          dataKey="month"
          tick={{ fontSize: 11, fill: 'hsl(210 15% 40%)' }}
          tickLine={false}
        />
        <YAxis
          tick={{ fontSize: 11, fill: 'hsl(210 15% 40%)' }}
          tickLine={false}
          axisLine={false}
          allowDecimals={false}
        />
        <Tooltip
          cursor={{ stroke: 'hsl(210 10% 85%)' }}
          contentStyle={{
            fontSize: '12px',
            borderRadius: '4px',
            border: '1px solid hsl(210 10% 85%)',
          }}
        />
        <Legend wrapperStyle={{ fontSize: '11px' }} />
        {palette.map((entry) => (
          <Area
            key={entry.key}
            type="monotone"
            dataKey={entry.key}
            name={entry.displayLabel}
            stackId="incidents-trend"
            stroke={entry.color}
            fill={entry.color}
            fillOpacity={0.55}
            isAnimationActive={false}
            data-testid={`${testIdPrefix}-series-${entry.key}`}
          />
        ))}
      </AreaChart>
    </section>
  )
}

export function MotivationStackedArea(): JSX.Element {
  return (
    <IncidentsStackedArea
      axis="motivation"
      i18nNamespace="dashboard.motivationStackedArea"
      testIdPrefix="motivation-stacked-area"
    />
  )
}

export function SectorStackedArea(): JSX.Element {
  return (
    <IncidentsStackedArea
      axis="sector"
      i18nNamespace="dashboard.sectorStackedArea"
      testIdPrefix="sector-stacked-area"
    />
  )
}

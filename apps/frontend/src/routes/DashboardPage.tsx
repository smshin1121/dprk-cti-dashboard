/**
 * /dashboard — protected landing. PR #13 Group I wiring.
 *
 * Layout mirrors design doc §4.2 areas [B] → [F]:
 *   [B] KPIStrip                                (top, full width)
 *   [C] WorldMap                                (left column, large)
 *   [D] AttackHeatmap + MotivationDonut + YearBar
 *   [E] TrendChart + GroupsMiniList + ReportFeed + SimilarReports
 *   [F] AlertsDrawer                            (trigger floats in header row)
 *
 * Every panel is self-contained and renders its own loading /
 * error / empty / populated states (plan D11). A fetch failure in
 * one panel degrades that panel, not the whole page. Plan D9
 * per-chart query separation is preserved:
 *   - KPIStrip / MotivationDonut / YearBar / GroupsMiniList share
 *     `/dashboard/summary` via `useDashboardSummary()` → ONE fetch
 *     across all four (summarySharedCache test pins this).
 *   - WorldMap consumes `useGeo()`.
 *   - AttackHeatmap consumes `useAttackMatrix()`.
 *   - TrendChart consumes `useTrend()`.
 *   - ReportFeed consumes `useReportsList()` (PR #12 hook).
 *   - SimilarReports is a Phase 3 stub (no data plumbing).
 *   - AlertsDrawer is a Phase 4 static shell (no data plumbing).
 */

import { AlertsDrawer } from '../features/dashboard/AlertsDrawer'
import { AttackHeatmap } from '../features/dashboard/AttackHeatmap'
import { GroupsMiniList } from '../features/dashboard/GroupsMiniList'
import { KPIStrip } from '../features/dashboard/KPIStrip'
import { MotivationDonut } from '../features/dashboard/MotivationDonut'
import { ReportFeed } from '../features/dashboard/ReportFeed'
import { SimilarReports } from '../features/dashboard/SimilarReports'
import { TrendChart } from '../features/dashboard/TrendChart'
import { WorldMap } from '../features/dashboard/WorldMap'
import { YearBar } from '../features/dashboard/YearBar'

export function DashboardPage(): JSX.Element {
  return (
    <section
      data-testid="dashboard-page"
      aria-labelledby="dashboard-heading"
      className="flex flex-col gap-6 p-6"
    >
      <h1 id="dashboard-heading" className="sr-only">
        Dashboard
      </h1>

      {/* [B] KPI strip — full width */}
      <KPIStrip />

      {/* [F] alerts drawer — trigger sits above the main grid;
          the panel itself slides in fixed-positioned */}
      <div className="flex justify-end">
        <AlertsDrawer />
      </div>

      {/* [C] + [D] top grid — world map left, ATT&CK right, with
          donut + year bar sharing the right column below */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <WorldMap />
        </div>
        <div className="lg:col-span-1">
          <AttackHeatmap />
        </div>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <MotivationDonut />
        <YearBar />
      </div>

      {/* [E] bottom grid — trend + groups + feed + similar */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <TrendChart />
        <GroupsMiniList />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <ReportFeed />
        <SimilarReports />
      </div>
    </section>
  )
}

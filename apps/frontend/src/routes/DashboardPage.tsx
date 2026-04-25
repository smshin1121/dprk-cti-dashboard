/**
 * /dashboard — protected landing. PR #13 Group I wiring; PR #14
 * Group F removed the SimilarReports stub (migrated to a live panel
 * on `ReportDetailPage`); PR #23 Group C added four lazarus.day-
 * parity panels integrated into the existing grid (no structural
 * re-layout).
 *
 * Layout mirrors design doc §4.2 areas [B] → [F]:
 *   [B] KPIStrip                                (top, full width)
 *   [C] WorldMap + AttackHeatmap                (split row)
 *   [D] MotivationDonut + YearBar               (ranked slice — row 1)
 *       SectorBreakdown + ContributorsList      (ranked slice — row 2, PR #23 §6.C C9+C6)
 *   [E] TrendChart + GroupsMiniList             (time series — row 1)
 *       MotivationStackedArea + SectorStackedArea (time series — row 2, PR #23 §6.C C7+C8)
 *       ReportFeed                              (full-width)
 *   [F] AlertsDrawer                            (trigger floats above grid)
 *
 * Every panel is self-contained and renders its own loading /
 * error / empty / populated states (plan D11). A fetch failure in
 * one panel degrades that panel, not the whole page. Plan D9
 * per-chart query separation is preserved:
 *   - KPIStrip / MotivationDonut / YearBar / GroupsMiniList /
 *     SectorBreakdown / ContributorsList all share
 *     `/dashboard/summary` via `useDashboardSummary()` → ONE fetch
 *     across all six (summarySharedCache + DashboardPage tests pin
 *     this invariant).
 *   - WorldMap consumes `useGeo()`.
 *   - AttackHeatmap consumes `useAttackMatrix()`.
 *   - TrendChart consumes `useTrend()` (reports fact table).
 *   - MotivationStackedArea + SectorStackedArea each consume
 *     `useIncidentsTrend({groupBy})` (incidents fact table) on
 *     separate cache slots per axis (PR #23 §6.A C1).
 *   - ReportFeed consumes `useReportsList()` (PR #12 hook).
 *   - AlertsDrawer is a Phase 4 static shell (no data plumbing).
 *
 * Similar-reports surface: lives on `ReportDetailPage`, not here.
 * The dashboard has no "selected report" context, so "similar to
 * what?" has no anchor at this scope; the panel is keyed on the
 * detail route's path-param id instead.
 */

import { AlertsDrawer } from '../features/dashboard/AlertsDrawer'
import { AttackHeatmap } from '../features/dashboard/AttackHeatmap'
import { ContributorsList } from '../features/dashboard/ContributorsList'
import { GroupsMiniList } from '../features/dashboard/GroupsMiniList'
import {
  MotivationStackedArea,
  SectorStackedArea,
} from '../features/dashboard/IncidentsStackedArea'
import { KPIStrip } from '../features/dashboard/KPIStrip'
import { MotivationDonut } from '../features/dashboard/MotivationDonut'
import { ReportFeed } from '../features/dashboard/ReportFeed'
import { SectorBreakdown } from '../features/dashboard/SectorBreakdown'
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

      {/* [C] + [D] top grid — world map left, ATT&CK right */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <WorldMap />
        </div>
        <div className="lg:col-span-1">
          <AttackHeatmap />
        </div>
      </div>

      {/* [D] ranked slice band — existing donut/yearbar PLUS the two
          new lazarus.day-parity ranked panels (PR #23 §6.C C9+C6). */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <MotivationDonut />
        <YearBar />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <SectorBreakdown />
        <ContributorsList />
      </div>

      {/* [E] time-series band — existing trend/groups PLUS the two
          new incidents-axis stacked-area widgets (PR #23 §6.C C7+C8). */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <TrendChart />
        <GroupsMiniList />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <MotivationStackedArea />
        <SectorStackedArea />
      </div>
      <ReportFeed />
    </section>
  )
}

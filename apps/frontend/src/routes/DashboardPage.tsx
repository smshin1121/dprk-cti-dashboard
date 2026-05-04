/**
 * /dashboard — analyst workspace per `docs/plans/dashboard-workspace-
 * retrofit.md` v1.2 (T9 relayout) + DESIGN.md `## Dashboard Workspace
 * Pattern` (locked by PR #32).
 *
 * 3-pane composition (rails INSIDE this page; Shell.tsx is unchanged
 * per L1 architectural lock; Shell.architectural-guard.test.tsx pins
 * the contract):
 *   - DashboardLeftRail   (240px) — section anchors / pinned / quick filter
 *   - center column       (flex-1) — heading row + center widget grid
 *   - DashboardRightRail  (320px) — alerts-rail + recent-activity + drilldown
 *
 * Center widget topology preserved (one new card slot added):
 *   [HEADING] dashboard-heading-row + PeriodReadout right-aligned (h-12)
 *   [B]       KPIStrip                                    (full width)
 *   [C]       WorldMap + AttackHeatmap                    (split row)
 *   [SLOT]    actor-network-graph (RESERVED / FUTURE)     (full-width text-only empty state)
 *   [C']      LocationsRanked                             (geo accessibility companion)
 *   [D]       MotivationDonut + YearBar                   (ranked slice — row 1)
 *             SectorBreakdown + ContributorsList          (ranked slice — row 2)
 *   [E]       TrendChart + GroupsMiniList                 (time series — row 1)
 *             MotivationStackedArea + SectorStackedArea   (time series — row 2)
 *             ReportFeed                                  (full-width)
 *
 * Removed by this PR:
 *   - DashboardHero (T9 unmounts; T10 deletes the file + its test)
 *   - AlertsDrawer (T7 deleted — replaced by AlertsRailSection inside
 *     DashboardRightRail)
 *
 * Per-cache-slot subscriber count (preserved):
 *   - KPIStrip / MotivationDonut / YearBar / GroupsMiniList /
 *     SectorBreakdown / ContributorsList all share
 *     `/dashboard/summary` via `useDashboardSummary()` (6 subscribers
 *     after hero unmount; summarySharedCache.test.tsx file count drops
 *     7 → 6 in T10 when the file is deleted).
 *   - WorldMap + LocationsRanked share `useGeo()`.
 *   - AttackHeatmap consumes `useAttackMatrix()`.
 *   - TrendChart consumes `useTrend()`.
 *   - MotivationStackedArea + SectorStackedArea consume
 *     `useIncidentsTrend({groupBy})` on separate cache slots per axis.
 *   - ReportFeed consumes `useReportsList()`.
 *   - AlertsRailSection / RecentActivity / Drilldown / ActorNetwork
 *     slot are all Phase 4 static shells (no data plumbing).
 *
 * Reserved-slot text-only discipline (DESIGN.md G5 #2 + actor-network-
 * graph vocabulary entry): the ActorNetwork slot renders title + the
 * literal `Planned · no data yet` empty state. NO svg / canvas /
 * synthetic nodes / edges / skeleton / sparkline / chart marks. PR 3
 * fills the slot with the live SNA visualization.
 */

import { AttackHeatmap } from '../features/dashboard/AttackHeatmap'
import { ContributorsList } from '../features/dashboard/ContributorsList'
import { DashboardLeftRail } from '../features/dashboard/DashboardLeftRail'
import { DashboardRightRail } from '../features/dashboard/DashboardRightRail'
import { GroupsMiniList } from '../features/dashboard/GroupsMiniList'
import {
  MotivationStackedArea,
  SectorStackedArea,
} from '../features/dashboard/IncidentsStackedArea'
import { KPIStrip } from '../features/dashboard/KPIStrip'
import { LocationsRanked } from '../features/dashboard/LocationsRanked'
import { MotivationDonut } from '../features/dashboard/MotivationDonut'
import { ReportFeed } from '../features/dashboard/ReportFeed'
import { SectorBreakdown } from '../features/dashboard/SectorBreakdown'
import { TrendChart } from '../features/dashboard/TrendChart'
import { WorldMap } from '../features/dashboard/WorldMap'
import { YearBar } from '../features/dashboard/YearBar'
import { PeriodReadout } from '../layout/PeriodReadout'

export function DashboardPage(): JSX.Element {
  return (
    <section
      data-testid="dashboard-page"
      aria-labelledby="dashboard-heading"
      className="flex min-h-screen"
    >
      <DashboardLeftRail />

      <div className="flex flex-1 flex-col gap-6 p-6">
        <header
          data-testid="dashboard-heading-row"
          className="flex h-12 items-center justify-between gap-4"
        >
          <h1
            id="dashboard-heading"
            className="text-xl font-semibold tracking-tight text-ink"
          >
            Threat Overview
          </h1>
          <PeriodReadout />
        </header>

        {/* [B] KPI strip — full width */}
        <KPIStrip />

        {/* [C] top grid — world map left, ATT&CK right */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <WorldMap />
          </div>
          <div className="lg:col-span-1">
            <AttackHeatmap />
          </div>
        </div>

        {/* [SLOT] actor-network-graph — RESERVED / FUTURE per DESIGN.md
            ## Dashboard Workspace Pattern > actor-network-graph
            vocabulary entry. Card chrome + title + text-only
            `Planned · no data yet` empty state. NO svg / canvas /
            synthetic nodes-edges / skeleton chart / sparkline.
            PR 3 wires the live SNA visualization. */}
        <section
          data-testid="actor-network-graph-slot"
          aria-labelledby="actor-network-graph-heading"
          className="rounded-none border border-border-card bg-surface p-4"
        >
          <h3
            id="actor-network-graph-heading"
            data-testid="actor-network-graph-title"
            className="mb-3 text-sm font-semibold text-ink"
          >
            Actor network · co-occurrence
          </h3>
          <p
            data-testid="actor-network-graph-empty-state"
            className="text-sm text-ink-muted"
          >
            Planned · no data yet
          </p>
        </section>

        {/* PR #23 §6.C C10 — LocationsRanked sits below the WorldMap
            row as a sortable, accessible companion list to the geo
            visualization. Same `useGeo()` cache slot — no extra
            /analytics/geo round-trip. */}
        <LocationsRanked />

        {/* [D] ranked slice band — donut/yearbar + sector/contributors */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <MotivationDonut />
          <YearBar />
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <SectorBreakdown />
          <ContributorsList />
        </div>

        {/* [E] time-series band — trend/groups + incidents stacked-area */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <TrendChart />
          <GroupsMiniList />
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <MotivationStackedArea />
          <SectorStackedArea />
        </div>
        <ReportFeed />
      </div>

      <DashboardRightRail />
    </section>
  )
}

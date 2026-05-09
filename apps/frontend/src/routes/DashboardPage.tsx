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
 *   [HEADING] dashboard-heading-row + PeriodReadout right-aligned (h-md, {spacing.md} = 32px per DESIGN.md ## Dashboard Workspace Pattern > Pane Geometry)
 *   [B]       KPIStrip                                    (full width)
 *   [C]       WorldMap + AttackHeatmap                    (split row)
 *   [SLOT]    actor-network-graph (live, PR 3)            (full-width SNA — d3-force layout, empty-state preserved)
 *   [C']      LocationsRanked                             (geo accessibility companion)
 *   [D]       MotivationDonut + YearBar                   (ranked slice — row 1)
 *             SectorBreakdown + ContributorsList          (ranked slice — row 2)
 *   [E]       TrendChart + GroupsMiniList                 (time series — row 1)
 *             MotivationStackedArea + SectorStackedArea   (time series — row 2)
 *             ReportFeed                                  (full-width)
 *
 * Removed by this PR:
 *   - DashboardHero (deprecated by PR #32 amendment; T9 unmounted +
 *     T10 deleted the file + its test)
 *   - AlertsDrawer (T7 deleted — replaced by AlertsRailSection inside
 *     DashboardRightRail)
 *
 * Per-cache-slot subscriber count (preserved):
 *   - KPIStrip / MotivationDonut / YearBar / GroupsMiniList /
 *     SectorBreakdown / ContributorsList all share
 *     `/dashboard/summary` via `useDashboardSummary()` — 6 subscribers,
 *     ONE fetch (summarySharedCache.test.tsx pins this).
 *   - WorldMap + LocationsRanked share `useGeo()`.
 *   - AttackHeatmap consumes `useAttackMatrix()`.
 *   - TrendChart consumes `useTrend()`.
 *   - MotivationStackedArea + SectorStackedArea consume
 *     `useIncidentsTrend({groupBy})` on separate cache slots per axis.
 *   - ReportFeed consumes `useReportsList()`.
 *   - AlertsRailSection / RecentActivity / Drilldown remain Phase 4
 *     static shells (no data plumbing).
 *   - ActorNetworkGraph subscribes to `useActorNetwork()` (its own
 *     React Query slot — does NOT join `summarySharedCache`; pinned
 *     by `ActorNetworkGraph.architectural-guard.test.tsx`).
 *
 * Reserved-slot empty-state discipline preserved (DESIGN.md G5 #2 +
 * actor-network-graph vocabulary entry): when the BE returns
 * `nodes: []`, ActorNetworkGraph renders the literal `Planned · no
 * data yet` empty state with NO svg / canvas / synthetic marks
 * (pinned by `ActorNetworkGraph.test.tsx` negative assertion). The
 * populated branch renders d3-force-laid-out SVG with degree-
 * centrality node sizing per kind.
 */

import { useTranslation } from 'react-i18next'

import { ActorNetworkGraph } from '../features/dashboard/ActorNetworkGraph'
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
  const { t } = useTranslation()
  return (
    <section
      data-testid="dashboard-page"
      data-page-class="analyst-workspace"
      aria-labelledby="dashboard-heading"
      className="flex min-h-screen flex-col lg:flex-row"
    >
      <DashboardLeftRail />

      <div className="flex flex-1 flex-col gap-6 px-lg py-md">
        <header
          data-testid="dashboard-heading-row"
          className="flex h-md items-center justify-between gap-4"
        >
          <h1
            id="dashboard-heading"
            className="text-xl font-semibold tracking-tight text-ink"
          >
            {t('dashboard.heading.threatOverview')}
          </h1>
          <PeriodReadout />
        </header>

        {/* [B] KPI strip — full width. id="overview" is the
            in-page scroll target for the left-rail "Overview" anchor
            (DESIGN.md ## Dashboard Workspace Pattern). */}
        <div id="overview" className="scroll-mt-16">
          <KPIStrip />
        </div>

        {/* [C] top grid — world map left, ATT&CK right.
            id="geo" is the in-page scroll target for the left-rail
            "Geo" anchor. */}
        <div
          id="geo"
          className="grid scroll-mt-16 grid-cols-1 gap-4 lg:grid-cols-3"
        >
          <div className="lg:col-span-2">
            <WorldMap />
          </div>
          <div className="lg:col-span-1">
            <AttackHeatmap />
          </div>
        </div>

        {/* PR 3 T10 — replaces the L6 reserved-slot text-only block
            with the live actor-network co-occurrence graph.
            ActorNetworkGraph preserves the slot/title/empty-state
            testids (workspace tests pin them via DashboardPage.workspace.test.tsx)
            and falls back to the same `Planned · no data yet` empty
            state when nodes.length === 0. */}
        <ActorNetworkGraph />

        {/* PR #23 §6.C C10 — LocationsRanked sits below the WorldMap
            row as a sortable, accessible companion list to the geo
            visualization. Same `useGeo()` cache slot — no extra
            /analytics/geo round-trip. */}
        <LocationsRanked />

        {/* [D] ranked slice band — donut/yearbar + sector/contributors.
            id="motivation" / id="sectors" are scroll targets for the
            left-rail "Motivation" / "Sectors" anchors. */}
        <div
          id="motivation"
          className="grid scroll-mt-16 grid-cols-1 gap-4 md:grid-cols-2"
        >
          <MotivationDonut />
          <YearBar />
        </div>
        <div
          id="sectors"
          className="grid scroll-mt-16 grid-cols-1 gap-4 md:grid-cols-2"
        >
          <SectorBreakdown />
          <ContributorsList />
        </div>

        {/* [E] time-series band — trend/groups + incidents stacked-area.
            id="trends" is the scroll target for the left-rail "Trends"
            anchor. */}
        <div
          id="trends"
          className="grid scroll-mt-16 grid-cols-1 gap-4 md:grid-cols-2"
        >
          <TrendChart />
          <GroupsMiniList />
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <MotivationStackedArea />
          <SectorStackedArea />
        </div>
        {/* id="reports" is the scroll target for the left-rail
            "Reports" anchor — pinned to the ReportFeed band. */}
        <div id="reports" className="scroll-mt-16">
          <ReportFeed />
        </div>
      </div>

      <DashboardRightRail />
    </section>
  )
}

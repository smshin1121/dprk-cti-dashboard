/**
 * AlertsRailSection — right-rail static alerts section per
 * `docs/plans/dashboard-workspace-retrofit.md` L4 / T7 + DESIGN.md
 * `## Dashboard Workspace Pattern > ### Right-Rail Surfaces >
 * alerts-rail-section`.
 *
 * In-place rewrite of the former AlertsDrawer (T0 inventory confirmed
 * zero non-dashboard production consumers, so the floating drawer
 * pattern is removed entirely). Phase 4 will replace the empty state
 * with a hook-driven list; the title + Phase 4 pill scaffolding stays.
 *
 * Reserved-slot text-only discipline (DESIGN.md G5 #2 + reserved-slot
 * Don't bullet): NO mock rows, NO synthetic dot+label+timestamp tuples,
 * NO skeleton charts, NO sparklines. Until live wiring lands, the
 * section renders title + Phase 4 pill + a single empty-state line.
 *
 * Layer rule (L1): mounted by DashboardRightRail (or transitionally
 * by DashboardPage during T7-T8 before T9 relayout). `Shell.tsx` MUST
 * NOT import this file (T5 static-source guard pins the contract;
 * `__tests__/Shell.architectural-guard.test.tsx` already names
 * AlertsRailSection in its forbidden-imports list).
 *
 * Purity: NO data fetches. Phase 4 wires the live alerts feed.
 *
 * i18n: T7 hardcodes user-visible strings. T11 swaps to
 * `dashboard.alerts.title` / `dashboard.alerts.phase4Pill` /
 * `dashboard.alerts.emptyState` (per L11).
 */

export function AlertsRailSection(): JSX.Element {
  return (
    <section
      data-testid="alerts-rail-section"
      data-phase-status="static-shell"
      data-phase="phase-4"
      aria-labelledby="alerts-rail-heading"
      className="flex flex-col gap-2 border-b border-border-card px-4 py-3"
    >
      <header className="flex items-center justify-between gap-2">
        <h3
          id="alerts-rail-heading"
          data-testid="alerts-rail-title"
          className="text-[10px] font-cta uppercase tracking-caption text-ink-subtle"
        >
          Alerts
        </h3>
        <span
          data-testid="alerts-rail-phase4-pill"
          className="rounded-none border border-border-card bg-app px-2 py-0.5 text-[10px] font-cta uppercase tracking-caption text-ink-muted"
        >
          Phase 4
        </span>
      </header>
      <p
        data-testid="alerts-rail-empty-state"
        className="text-xs text-ink-muted"
      >
        Phase 4 — no live alerts wired yet
      </p>
    </section>
  )
}

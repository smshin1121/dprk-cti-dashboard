/**
 * AlertsRailSection — right-rail static alerts section per
 * `docs/plans/dashboard-workspace-retrofit.md` L4 / T7 + DESIGN.md
 * `## Dashboard Workspace Pattern > ### Right-Rail Surfaces >
 * alerts-rail-section`.
 *
 * Replaces the former `AlertsDrawer.tsx` (DELETE + ADD in the diff —
 * see body draft §0.1 amendment 4). T0 inventory confirmed zero
 * non-dashboard production consumers, so the floating drawer pattern
 * is removed entirely; the new filename matches the new role inside
 * the right rail. Phase 4 will replace the empty state with a
 * hook-driven list; the title + Phase 4 pill scaffolding stays.
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
 * i18n: title via `dashboard.alerts.title` (carried over from the
 * deleted AlertsDrawer; pre-existing in both locales). Phase 4 pill
 * via `dashboard.alerts.phase4Pill` and empty-state line via
 * `dashboard.alerts.emptyState` per L11 (T11).
 */

import { useTranslation } from 'react-i18next'

export function AlertsRailSection(): JSX.Element {
  const { t } = useTranslation()
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
          {t('dashboard.alerts.title')}
        </h3>
        <span
          data-testid="alerts-rail-phase4-pill"
          className="rounded-none border border-border-card bg-app px-2 py-0.5 text-[10px] font-cta uppercase tracking-caption text-ink-muted"
        >
          {t('dashboard.alerts.phase4Pill')}
        </span>
      </header>
      <p
        data-testid="alerts-rail-empty-state"
        className="text-xs text-ink-muted"
      >
        {t('dashboard.alerts.emptyState')}
      </p>
    </section>
  )
}

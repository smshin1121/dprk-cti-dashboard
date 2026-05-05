/**
 * DashboardRightRail — right rail for the `/dashboard` analyst workspace
 * per `docs/plans/dashboard-workspace-retrofit.md` L4 / T4 + DESIGN.md
 * `## Dashboard Workspace Pattern > ### Right-Rail Surfaces`.
 *
 * Composition (top → bottom):
 *   - alerts-rail-section (mounted via the converted AlertsRailSection
 *     component; static Phase 4 shell)
 *   - recent-activity-list (static Phase 4 shell — no live activity
 *     feed in PR 2)
 *   - drilldown-empty-state (Phase 4 honesty copy: "Phase 4 — drilldown
 *     not wired yet". The pre-Codex-r1 "Select an item from a center
 *     list to inspect here" prompt is BANNED because PR 2 does not wire
 *     selection-driven drilldown — the prompt would lie about
 *     interactivity.)
 *
 * Reserved-slot text-only discipline (DESIGN.md G5 #2): NO mock rows,
 * NO synthetic dot+label+timestamp tuples, NO skeleton charts, NO
 * sparklines. All three surfaces render title + Phase-4-disclosed
 * empty state until Phase 4 wires real data.
 *
 * Layer rule (L1): mounted directly inside `DashboardPage.tsx` (T9).
 * `Shell.tsx` MUST NOT import this file (T5 static-source guard pins
 * the contract).
 *
 * Purity: NO live data fetches at mount. Phase 4 wires real feeds.
 *
 * i18n: AlertsRailSection owns its own keys; the local recent +
 * drilldown empty-state lines wire `dashboard.recent.emptyState` /
 * `dashboard.drilldown.emptyState` per L11 (T11). The "Recent
 * activity" + "Drilldown" titles are rendered as English literals —
 * they are not in the locked L11 9-key list and get keys in a
 * follow-up sweep.
 *
 * Caption-title parity (Codex PR #33 r1 F2): per DESIGN.md
 * `## Dashboard Workspace Pattern` — `Both recent-activity-list and
 * drilldown-empty-state reuse the caption-uppercase title +
 * empty-state line pattern from alerts-rail-section`. Drilldown
 * mounts a `<h3>` caption + aria-labelledby wiring on the section so
 * all three right-rail blocks share anatomy.
 */

import { useTranslation } from 'react-i18next'

import { AlertsRailSection } from './AlertsRailSection'

export function DashboardRightRail(): JSX.Element {
  const { t } = useTranslation()
  return (
    <aside
      data-testid="dashboard-right-rail"
      className="flex w-full flex-col border-t border-border-card bg-surface text-sm lg:w-80 lg:shrink-0 lg:border-l lg:border-t-0"
    >
      <AlertsRailSection />

      <section
        data-testid="recent-activity-list"
        aria-labelledby="recent-activity-heading"
        className="flex flex-col gap-2 border-b border-border-card px-4 py-3"
      >
        <h3
          id="recent-activity-heading"
          data-testid="recent-activity-title"
          className="text-[10px] font-cta uppercase tracking-caption text-ink-subtle"
        >
          Recent activity
        </h3>
        <p
          data-testid="recent-activity-empty-state"
          className="text-xs text-ink-muted"
        >
          {t('dashboard.recent.emptyState')}
        </p>
      </section>

      <section
        data-testid="drilldown-empty-state"
        aria-labelledby="drilldown-heading"
        className="flex flex-col gap-2 px-4 py-3"
      >
        <h3
          id="drilldown-heading"
          data-testid="drilldown-title"
          className="text-[10px] font-cta uppercase tracking-caption text-ink-subtle"
        >
          Drilldown
        </h3>
        <p className="text-xs text-ink-muted">
          {t('dashboard.drilldown.emptyState')}
        </p>
      </section>
    </aside>
  )
}

/**
 * DashboardLeftRail — left rail for the `/dashboard` analyst workspace
 * per `docs/plans/dashboard-workspace-retrofit.md` L3 / T3 + DESIGN.md
 * `## Dashboard Workspace Pattern > ### Pane Geometry`.
 *
 * Composition:
 *   - Sections — in-page anchors (Overview / Geo / Motivation / Sectors
 *     / Trends / Reports). The active section row carries the PT-5
 *     1px Rosso left-edge stripe (`border-l border-l-signal`); inactive
 *     rows use a transparent left border so the row geometry stays
 *     stable (no layout shift on activation).
 *   - Pinned — static list of analyst-favorited actors (APT37 / Lazarus
 *     for T7; full pinning UX is Phase 4 deferred).
 *   - Quick filter — three data-backed checkboxes (This week / Has
 *     linked actor / Has incidents). All unchecked by default; live
 *     wiring to the filter store is Phase 4 deferred (T7 ships static
 *     UI per DESIGN.md reserved-slot text-only rule).
 *
 * Layer rule (L1): mounted directly inside `DashboardPage.tsx`.
 * `Shell.tsx` MUST NOT import this file (T5 static-source guard pins
 * the contract).
 *
 * Purity: NO live data fetches at mount. Sections + Pinned + Quick
 * filter are static for T7. Phase 4 wires real data.
 *
 * i18n: left-rail labels (Sections / Pinned / Quick filter group
 * titles + 6 anchor labels + 2 pinned actor names + 3 quick-filter
 * checkbox labels) are intentionally hardcoded English literals and
 * are out of scope for plan §4 T11. The L11 9-key contract covers
 * heading row + period readout + alerts/recent/drilldown empty states
 * + actor-network slot only; broader nav-label i18n is deferred to a
 * separate follow-up sweep.
 */

import type { ReactNode } from 'react'

interface SectionAnchor {
  readonly id: string
  readonly label: string
  readonly href: string
  readonly active: boolean
}

const SECTIONS: readonly SectionAnchor[] = [
  { id: 'overview', label: 'Overview', href: '#overview', active: true },
  { id: 'geo', label: 'Geo', href: '#geo', active: false },
  { id: 'motivation', label: 'Motivation', href: '#motivation', active: false },
  { id: 'sectors', label: 'Sectors', href: '#sectors', active: false },
  { id: 'trends', label: 'Trends', href: '#trends', active: false },
  { id: 'reports', label: 'Reports', href: '#reports', active: false },
]

const PINNED_ACTORS = ['APT37', 'Lazarus'] as const

interface QuickFilterOption {
  readonly id: string
  readonly label: string
}

const QUICK_FILTERS: readonly QuickFilterOption[] = [
  { id: 'thisWeek', label: 'This week' },
  { id: 'hasLinkedActor', label: 'Has linked actor' },
  { id: 'hasIncidents', label: 'Has incidents' },
]

export function DashboardLeftRail(): JSX.Element {
  return (
    <aside
      data-testid="dashboard-left-rail"
      className="flex w-full flex-col gap-6 border-b border-border-card bg-surface p-4 text-sm lg:w-60 lg:shrink-0 lg:border-b-0 lg:border-r"
    >
      <RailGroup title="Sections" testid="left-rail-sections">
        <ul className="flex flex-col">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a
                href={s.href}
                data-testid={
                  s.active
                    ? 'left-rail-section-active'
                    : `left-rail-section-inactive-${s.id}`
                }
                className={
                  s.active
                    ? 'block border-l border-l-signal py-1 pl-3 text-ink'
                    : 'block border-l border-l-transparent py-1 pl-3 text-ink-muted'
                }
              >
                {s.label}
              </a>
            </li>
          ))}
        </ul>
      </RailGroup>

      <RailGroup title="Pinned" testid="left-rail-pinned">
        <ul className="flex flex-col gap-1">
          {PINNED_ACTORS.map((actor) => (
            <li key={actor} className="text-ink-muted">
              {actor}
            </li>
          ))}
        </ul>
      </RailGroup>

      <RailGroup title="Quick filter" testid="left-rail-quick-filter">
        <ul className="flex flex-col gap-1">
          {QUICK_FILTERS.map((q) => (
            <li key={q.id}>
              <label className="flex items-center gap-2 text-ink-muted">
                <input
                  type="checkbox"
                  defaultChecked={false}
                  data-testid={`left-rail-quick-filter-${q.id}`}
                  className="h-3 w-3 accent-signal"
                />
                {q.label}
              </label>
            </li>
          ))}
        </ul>
      </RailGroup>
    </aside>
  )
}

interface RailGroupProps {
  readonly title: string
  readonly testid: string
  readonly children: ReactNode
}

function RailGroup({ title, testid, children }: RailGroupProps): JSX.Element {
  return (
    <section data-testid={testid} className="flex flex-col gap-2">
      <span className="text-[10px] font-cta uppercase tracking-caption text-ink-subtle">
        {title}
      </span>
      {children}
    </section>
  )
}

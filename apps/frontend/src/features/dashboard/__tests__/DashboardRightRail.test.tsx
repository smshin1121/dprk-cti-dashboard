/**
 * DashboardRightRail — RED tests (PR 2 T4).
 *
 * Component contract per `docs/plans/dashboard-workspace-retrofit.md` L4 / T4
 * + DESIGN.md `## Dashboard Workspace Pattern > ### Right-Rail Surfaces`:
 *
 *   Right rail = alerts-rail-section + recent-activity-list +
 *   drilldown-empty-state. All three are reserved-slot disciplined:
 *   no mock rows, no fabricated data, no synthetic dot+label+timestamp
 *   tuples. Title + Phase-4 pill + single empty-state line each.
 *   drilldown copy = exactly "Phase 4 — drilldown not wired yet".
 *
 * The right rail consumes a converted AlertsRailSection (T7 — converted
 * from AlertsDrawer in-place per Codex F7 fold; no extracted file
 * because AlertsDrawer has 0 non-dashboard production consumers per
 * Codex Q7).
 *
 * RED phase: DashboardRightRail.tsx does not exist yet. T7 GREEN.
 */

import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// Side-effect import: AlertsRailSection (mounted via DashboardRightRail)
// reuses the existing `dashboard.alerts.title` key via useTranslation,
// so the i18n bootstrap must initialize before render in this isolated
// suite. Without it react-i18next emits a NO_I18NEXT_INSTANCE warning
// and t() falls back to returning the literal key.
import '../../../i18n'

import { DashboardRightRail } from '../DashboardRightRail'

describe('DashboardRightRail', () => {
  it('renders the rail container with testid', () => {
    render(<DashboardRightRail />)
    expect(screen.getByTestId('dashboard-right-rail')).toBeInTheDocument()
  })

  it('renders three sections: alerts-rail / recent-activity / drilldown-empty', () => {
    render(<DashboardRightRail />)
    expect(screen.getByTestId('alerts-rail-section')).toBeInTheDocument()
    expect(screen.getByTestId('recent-activity-list')).toBeInTheDocument()
    expect(screen.getByTestId('drilldown-empty-state')).toBeInTheDocument()
  })

  it('alerts-rail-section shows title + Phase 4 pill + single empty-state line; ZERO mock rows', () => {
    render(<DashboardRightRail />)
    const alerts = screen.getByTestId('alerts-rail-section')
    expect(within(alerts).getByTestId('alerts-rail-title')).toBeInTheDocument()
    expect(within(alerts).getByTestId('alerts-rail-phase4-pill')).toHaveTextContent(
      /phase\s*4/i,
    )
    expect(within(alerts).getByTestId('alerts-rail-empty-state')).toHaveTextContent(
      /no live alerts wired yet|no live alerts/i,
    )
    // CRITICAL discipline: zero mock rows. Production tree must not
    // synthesize dot+label+timestamp tuples even for visual rhythm.
    // Per DESIGN.md G5 #2 + alerts-rail-section vocabulary entry.
    expect(within(alerts).queryAllByTestId(/^alerts-rail-mock-row/)).toHaveLength(0)
    expect(within(alerts).queryAllByTestId('alerts-rail-row')).toHaveLength(0)
  })

  it('recent-activity-list shows title + Phase 4 empty-state line; ZERO mock rows', () => {
    render(<DashboardRightRail />)
    const recent = screen.getByTestId('recent-activity-list')
    expect(within(recent).getByTestId('recent-activity-title')).toBeInTheDocument()
    expect(within(recent).getByTestId('recent-activity-empty-state')).toHaveTextContent(
      /no activity wired yet|phase\s*4/i,
    )
    expect(within(recent).queryAllByTestId(/^recent-activity-mock-row/)).toHaveLength(0)
    expect(within(recent).queryAllByTestId('recent-activity-row')).toHaveLength(0)
  })

  it('drilldown-empty-state copy is exactly the contracted Phase-4 message (NOT a "Select an item..." prompt)', () => {
    render(<DashboardRightRail />)
    const drilldown = screen.getByTestId('drilldown-empty-state')
    // Codex r1 fold of PR #32 requires Phase-4 honesty discipline.
    // Old "Select an item from a center list to inspect here" is
    // banned because PR 2 does not wire selection-driven drilldown.
    expect(drilldown).toHaveTextContent(/phase\s*4/i)
    expect(drilldown).toHaveTextContent(/drilldown.*not wired yet/i)
    expect(drilldown).not.toHaveTextContent(/select an item/i)
  })

  it('drilldown-empty-state mounts a caption-uppercase title (DESIGN.md ## Dashboard Workspace Pattern parity with recent-activity)', () => {
    render(<DashboardRightRail />)
    const drilldown = screen.getByTestId('drilldown-empty-state')
    // Codex PR #33 r1 F2: drilldown must reuse the caption-uppercase
    // title + empty-state line pattern from alerts-rail-section, same
    // as recent-activity-list. The section labels itself via aria-
    // labelledby so screen readers announce the block heading.
    expect(drilldown).toHaveAttribute('aria-labelledby', 'drilldown-heading')
    const title = within(drilldown).getByTestId('drilldown-title')
    expect(title).toHaveAttribute('id', 'drilldown-heading')
    expect(title.tagName).toBe('H3')
    expect(title).toHaveTextContent(/drilldown/i)
    // caption-uppercase typography token: tracking-caption + uppercase.
    expect(title.className).toMatch(/uppercase/)
    expect(title.className).toMatch(/tracking-caption/)
  })

  it('does NOT fire any /api/* fetches at mount (right rail is purely presentational)', () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response('{}', { status: 200 })),
    )
    render(<DashboardRightRail />)
    const apiCalls = fetchSpy.mock.calls.filter(([url]) =>
      String(url).includes('/api/'),
    )
    expect(apiCalls).toHaveLength(0)
    fetchSpy.mockRestore()
  })
})

/**
 * DashboardLeftRail — RED tests (PR 2 T3).
 *
 * Component contract per `docs/plans/dashboard-workspace-retrofit.md` L3 / T3
 * + DESIGN.md `## Dashboard Workspace Pattern > ### Pane Geometry / Cross-References`:
 *
 *   Left-rail composition: Sections group (in-page anchors) +
 *   Pinned actors group + Quick filter group. Width 240px target.
 *   PT-5 1px Rosso left-edge stripe on active section row. Checkbox
 *   rows unchecked by default. No live data fetches at mount.
 *
 * RED phase: DashboardLeftRail.tsx does not exist yet. T7 GREEN.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DashboardLeftRail } from '../DashboardLeftRail'

describe('DashboardLeftRail', () => {
  it('renders the rail container with testid', () => {
    render(<DashboardLeftRail />)
    expect(screen.getByTestId('dashboard-left-rail')).toBeInTheDocument()
  })

  it('renders the three groups: Sections / Pinned actors / Quick filter', () => {
    render(<DashboardLeftRail />)
    expect(screen.getByTestId('left-rail-sections')).toBeInTheDocument()
    expect(screen.getByTestId('left-rail-pinned')).toBeInTheDocument()
    expect(screen.getByTestId('left-rail-quick-filter')).toBeInTheDocument()
  })

  it('Sections group includes the contracted anchor list (Overview, Geo, Motivation, Sectors, Trends, Reports)', () => {
    render(<DashboardLeftRail />)
    const sections = screen.getByTestId('left-rail-sections')
    expect(sections).toHaveTextContent(/overview/i)
    expect(sections).toHaveTextContent(/geo/i)
    expect(sections).toHaveTextContent(/motivation/i)
    expect(sections).toHaveTextContent(/sectors/i)
    expect(sections).toHaveTextContent(/trends/i)
    expect(sections).toHaveTextContent(/reports/i)
  })

  it('Quick filter shows the data-backed checkboxes (this week, has linked actor, has incidents) all UNCHECKED by default', () => {
    render(<DashboardLeftRail />)
    const quickFilter = screen.getByTestId('left-rail-quick-filter')
    const checkboxes = quickFilter.querySelectorAll<HTMLInputElement>(
      'input[type="checkbox"]',
    )
    expect(checkboxes.length).toBeGreaterThanOrEqual(3)
    checkboxes.forEach((cb) => {
      expect(cb.checked).toBe(false)
    })
  })

  it('active section anchor row carries PT-5 1px Rosso left-edge stripe class', () => {
    render(<DashboardLeftRail />)
    const activeRow = screen.getByTestId('left-rail-section-active')
    // PT-5 stripe on vertical surfaces. Tailwind utility class for
    // a 1px primary left border. Permitted patterns:
    //   border-l border-l-signal  (signal === Ferrari primary alias)
    //   border-l-2 border-l-signal (some impls use 2px; PT-5 says 1px)
    // The contract is 1px; assert the 1px form.
    expect(activeRow.className).toMatch(/\bborder-l\b/)
    expect(activeRow.className).toMatch(/\bborder-l-signal\b/)
    // Negative: no full-row primary fill (ban on full Rosso fill).
    expect(activeRow.className).not.toMatch(/\bbg-signal\b|\bbg-primary\b/)
  })

  it('inactive section anchor rows do NOT carry the Rosso stripe', () => {
    render(<DashboardLeftRail />)
    const inactiveRows = screen.getAllByTestId(/^left-rail-section-inactive/)
    expect(inactiveRows.length).toBeGreaterThan(0)
    inactiveRows.forEach((row) => {
      expect(row.className).not.toMatch(/\bborder-l-signal\b/)
    })
  })

  it('does NOT fire any /api/* fetches at mount (left rail is purely presentational)', () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(
      () => Promise.resolve(new Response('{}', { status: 200 })),
    )
    render(<DashboardLeftRail />)
    const apiCalls = fetchSpy.mock.calls.filter(([url]) =>
      String(url).includes('/api/'),
    )
    expect(apiCalls).toHaveLength(0)
    fetchSpy.mockRestore()
  })

  it('pinned actors group renders at least the two contracted entries (APT37, Lazarus)', () => {
    render(<DashboardLeftRail />)
    const pinned = screen.getByTestId('left-rail-pinned')
    expect(pinned).toHaveTextContent(/apt37/i)
    expect(pinned).toHaveTextContent(/lazarus/i)
  })
})

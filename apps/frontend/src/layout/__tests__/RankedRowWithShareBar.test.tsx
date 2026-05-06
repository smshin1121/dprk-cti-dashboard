/**
 * RankedRowWithShareBar — RED tests (PR 2 T2).
 *
 * Component contract per `docs/plans/dashboard-workspace-retrofit.md` L5 / L7 / T2
 * + DESIGN.md `## Dashboard Workspace Pattern > ### Center-Pane Widget Surfaces
 * > ranked-row-with-share-bar`:
 *
 *   Anatomy: 32×32 square avatar (canvas bg, body initials, 1px hairline
 *   border, rounded-none corners) + name (body) + sub (caption,
 *   muted-soft) + horizontal share-bar (4px height, body fill at 100%
 *   for top-item, scaled by relative share for lower rows; NEVER
 *   primary, NEVER chart palette) + value (tabular-nums) + percentage
 *   (caption, muted-soft).
 *
 * Used by 4 ranked panels (LocationsRanked / SectorBreakdown /
 * ContributorsList / GroupsMiniList). Each row is presentational —
 * consumers compute share/percentage and pass them as props.
 *
 * RED phase: RankedRowWithShareBar.tsx does not exist yet. T7 GREEN.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { RankedRowWithShareBar } from '../RankedRowWithShareBar'

const baseProps = {
  avatarText: 'KR',
  name: 'Korea, Republic of',
  sub: 'Government, Defense, Finance',
  value: '412',
  shareBarPct: 100,
  pct: '33%',
}

describe('RankedRowWithShareBar', () => {
  it('renders all anatomy elements with their testids', () => {
    render(<RankedRowWithShareBar {...baseProps} />)
    expect(screen.getByTestId('ranked-row')).toBeInTheDocument()
    expect(screen.getByTestId('ranked-row-avatar')).toHaveTextContent('KR')
    expect(screen.getByTestId('ranked-row-name')).toHaveTextContent(
      'Korea, Republic of',
    )
    expect(screen.getByTestId('ranked-row-sub')).toHaveTextContent(
      'Government, Defense, Finance',
    )
    expect(screen.getByTestId('ranked-row-bar-track')).toBeInTheDocument()
    expect(screen.getByTestId('ranked-row-bar-fill')).toBeInTheDocument()
    expect(screen.getByTestId('ranked-row-value')).toHaveTextContent('412')
    expect(screen.getByTestId('ranked-row-pct')).toHaveTextContent('33%')
  })

  it('avatar is 32×32 with hairline border, canvas bg, body initials, rounded-none', () => {
    render(<RankedRowWithShareBar {...baseProps} />)
    const avatar = screen.getByTestId('ranked-row-avatar')
    // 32×32 box (h-8 w-8 in Tailwind = 32px).
    expect(avatar.className).toMatch(/\bh-8\b/)
    expect(avatar.className).toMatch(/\bw-8\b/)
    // 1px hairline border.
    expect(avatar.className).toMatch(/\bborder\b/)
    expect(avatar.className).toMatch(/\bborder-border-card\b/)
    // Canvas (#181818) background.
    expect(avatar.className).toMatch(/\bbg-app\b/)
    // Body (#969696) initial color.
    expect(avatar.className).toMatch(/\btext-ink-muted\b|\btext-body\b/)
    // Sharp corners — Ferrari signature.
    expect(avatar.className).toMatch(/\brounded-none\b/)
    // Negative — must NOT be a circle (DashLite copy hazard).
    expect(avatar.className).not.toMatch(/\brounded-full\b/)
  })

  it('top-item share bar fill is 100% width; bar fill color is body, never primary', () => {
    render(<RankedRowWithShareBar {...baseProps} shareBarPct={100} />)
    const fill = screen.getByTestId('ranked-row-bar-fill')
    // Width prop projected to inline style.
    expect(fill).toHaveStyle({ width: '100%' })
    // Color discipline: body / ink-muted only. NOT signal/primary,
    // NOT chart palette.
    expect(fill.className).toMatch(/\bbg-ink-muted\b|\bbg-body\b|\bbg-muted\b/)
    expect(fill.className).not.toMatch(/\bbg-signal\b|\bbg-primary\b/)
    expect(fill.className).not.toMatch(/\bbg-chart-/)
  })

  it('lower-ranked row scales bar fill width to its relative share', () => {
    render(<RankedRowWithShareBar {...baseProps} shareBarPct={36} />)
    const fill = screen.getByTestId('ranked-row-bar-fill')
    expect(fill).toHaveStyle({ width: '36%' })
  })

  it('clamps shareBarPct out-of-range values to 0..100', () => {
    const { rerender } = render(
      <RankedRowWithShareBar {...baseProps} shareBarPct={150} />,
    )
    expect(screen.getByTestId('ranked-row-bar-fill')).toHaveStyle({
      width: '100%',
    })
    rerender(<RankedRowWithShareBar {...baseProps} shareBarPct={-10} />)
    expect(screen.getByTestId('ranked-row-bar-fill')).toHaveStyle({
      width: '0%',
    })
  })

  it('renders without sub when sub prop is omitted', () => {
    const { sub: _sub, ...withoutSub } = baseProps
    render(<RankedRowWithShareBar {...withoutSub} />)
    // Optional sub line; row still renders.
    expect(screen.getByTestId('ranked-row')).toBeInTheDocument()
    expect(screen.queryByTestId('ranked-row-sub')).toBeNull()
  })

  it('renders without pct when pct prop is omitted (panels that show absolute count only)', () => {
    const { pct: _pct, ...withoutPct } = baseProps
    render(<RankedRowWithShareBar {...withoutPct} />)
    expect(screen.getByTestId('ranked-row-value')).toHaveTextContent('412')
    expect(screen.queryByTestId('ranked-row-pct')).toBeNull()
  })

  it('value uses tabular-nums for column alignment across rows', () => {
    render(<RankedRowWithShareBar {...baseProps} />)
    const value = screen.getByTestId('ranked-row-value')
    expect(value.className).toMatch(/\btabular-nums\b/)
  })

  it('row container has hairline divider class (border-b border-border-card)', () => {
    render(<RankedRowWithShareBar {...baseProps} />)
    const row = screen.getByTestId('ranked-row')
    // Hairline between rows — Ferrari uses borders, never shadows.
    expect(row.className).toMatch(/\bborder-b\b/)
    expect(row.className).toMatch(/\bborder-border-card\b/)
  })

  it('row has no hover background class (hover state never documented per DESIGN Iteration Guide item 5)', () => {
    render(<RankedRowWithShareBar {...baseProps} />)
    const row = screen.getByTestId('ranked-row')
    // Negative assertion: no hover:bg-* utility on the row.
    expect(row.className).not.toMatch(/\bhover:bg-/)
  })
})

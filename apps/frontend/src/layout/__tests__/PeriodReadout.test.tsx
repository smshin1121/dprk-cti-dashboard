/**
 * PeriodReadout — RED tests (PR 2 T1).
 *
 * Component contract per `docs/plans/dashboard-workspace-retrofit.md` L7
 * + DESIGN.md `## Dashboard Workspace Pattern > ### Heading Row`:
 *
 *   - Read-only display of the active date range from the global
 *     FilterBar's store. Subscribes to useFilterStore for dateFrom +
 *     dateTo (camelCase store fields per Codex F3, NOT the
 *     date_from/date_to URL/wire names).
 *   - "Period" caption-uppercase label + date-range value (body) +
 *     "change in filter bar" hint (muted).
 *   - NEVER editable. No <input>, no setter, no click-to-edit.
 *
 * RED phase: this file describes the contract; PeriodReadout.tsx does
 * not exist yet. T7 turns these GREEN.
 */

import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useFilterStore } from '../../stores/filters'
import { PeriodReadout } from '../PeriodReadout'

function resetStore(): void {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
}

describe('PeriodReadout', () => {
  beforeEach(resetStore)

  it('renders the period testid and label', () => {
    render(<PeriodReadout />)
    expect(screen.getByTestId('period-readout')).toBeInTheDocument()
    // Caption-uppercase token discipline (Ferrari L1 typography).
    expect(screen.getByTestId('period-readout-label')).toHaveTextContent(
      /period/i,
    )
  })

  it('mirrors the store dateFrom/dateTo values', () => {
    useFilterStore.setState({ dateFrom: '2024-01-01', dateTo: '2026-05-04' })
    render(<PeriodReadout />)
    const value = screen.getByTestId('period-readout-value')
    expect(value).toHaveTextContent('2024-01-01')
    expect(value).toHaveTextContent('2026-05-04')
  })

  it('shows an "All time" fallback when both dates are null', () => {
    useFilterStore.setState({ dateFrom: null, dateTo: null })
    render(<PeriodReadout />)
    const value = screen.getByTestId('period-readout-value')
    // Empty state copy is intentionally generic; exact i18n key
    // resolves at GREEN time (T11). The test checks SOMETHING shows
    // — never a literal empty string.
    expect(value.textContent?.trim()).not.toBe('')
  })

  it('renders the "change in filter bar" hint glyph', () => {
    render(<PeriodReadout />)
    const hint = screen.getByTestId('period-readout-hint')
    expect(hint).toBeInTheDocument()
    // Muted color token discipline.
    expect(hint.className).toMatch(/\btext-(muted|ink-subtle|muted-soft)\b/)
  })

  it('is read-only — no input element, no setter on click, no role=button on the readout itself', () => {
    render(<PeriodReadout />)
    const readout = screen.getByTestId('period-readout')
    // L7 read-only contract: NO <input>, no <button> wrapping the
    // readout, no role=button anywhere inside.
    expect(readout.querySelector('input')).toBeNull()
    expect(readout.querySelector('button')).toBeNull()
    expect(
      readout.querySelectorAll('[role="button"]').length,
    ).toBe(0)
  })

  it('does not call setDateRange when the readout is clicked', async () => {
    const setDateRange = vi.spyOn(useFilterStore.getState(), 'setDateRange')
    render(<PeriodReadout />)
    const readout = screen.getByTestId('period-readout')
    readout.click()
    expect(setDateRange).not.toHaveBeenCalled()
  })

  it('updates when the store updates (live mirror)', () => {
    render(<PeriodReadout />)
    useFilterStore.setState({ dateFrom: '2025-06-01', dateTo: '2025-12-31' })
    const value = screen.getByTestId('period-readout-value')
    expect(value).toHaveTextContent('2025-06-01')
    expect(value).toHaveTextContent('2025-12-31')
  })
})

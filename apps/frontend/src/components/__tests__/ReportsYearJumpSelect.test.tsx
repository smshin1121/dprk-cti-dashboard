import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useFilterStore } from '../../stores/filters'
import { ReportsYearJumpSelect } from '../ReportsYearJumpSelect'

function reset(): void {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
}

beforeEach(reset)
afterEach(reset)

describe('ReportsYearJumpSelect', () => {
  it('lists "All years" + a descending year range starting at the current year and ending at 2009', () => {
    render(<ReportsYearJumpSelect />)
    const select = screen.getByTestId('reports-year-jump') as HTMLSelectElement
    const opts = Array.from(select.options).map((o) => o.value)
    expect(opts[0]).toBe('') // All years
    const currentYear = new Date().getFullYear()
    expect(opts[1]).toBe(String(currentYear))
    expect(opts.at(-1)).toBe('2009')
  })

  it('selecting a year sets dateFrom + dateTo to that full calendar year', async () => {
    render(<ReportsYearJumpSelect />)
    await userEvent
      .setup()
      .selectOptions(screen.getByTestId('reports-year-jump'), '2024')
    const state = useFilterStore.getState()
    expect(state.dateFrom).toBe('2024-01-01')
    expect(state.dateTo).toBe('2024-12-31')
  })

  it('selecting "All years" clears dateFrom + dateTo to null', async () => {
    useFilterStore.setState({ dateFrom: '2024-01-01', dateTo: '2024-12-31' })
    render(<ReportsYearJumpSelect />)
    await userEvent
      .setup()
      .selectOptions(screen.getByTestId('reports-year-jump'), '')
    const state = useFilterStore.getState()
    expect(state.dateFrom).toBeNull()
    expect(state.dateTo).toBeNull()
  })

  it('reflects an existing year-aligned date range as the selected option', () => {
    useFilterStore.setState({ dateFrom: '2025-01-01', dateTo: '2025-12-31' })
    render(<ReportsYearJumpSelect />)
    expect(
      (screen.getByTestId('reports-year-jump') as HTMLSelectElement).value,
    ).toBe('2025')
  })

  it('shows "Custom range" when the active range is not a full calendar year', () => {
    useFilterStore.setState({ dateFrom: '2025-06-01', dateTo: '2025-09-30' })
    render(<ReportsYearJumpSelect />)
    const select = screen.getByTestId('reports-year-jump') as HTMLSelectElement
    expect(select.value).toBe('custom')
    expect(screen.getByRole('option', { name: 'Custom range' })).toBeVisible()
  })

  it('selecting "All years" from a custom range clears dateFrom + dateTo', async () => {
    useFilterStore.setState({ dateFrom: '2025-06-01', dateTo: '2025-09-30' })
    render(<ReportsYearJumpSelect />)

    await userEvent
      .setup()
      .selectOptions(screen.getByTestId('reports-year-jump'), '')

    const state = useFilterStore.getState()
    expect(state.dateFrom).toBeNull()
    expect(state.dateTo).toBeNull()
  })
})

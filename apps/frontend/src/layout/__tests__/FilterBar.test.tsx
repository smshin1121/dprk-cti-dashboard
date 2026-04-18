import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { useFilterStore } from '../../stores/filters'
import { FilterBar, FILTER_GROUP_OPTIONS } from '../FilterBar'

function resetStore(): void {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
}

describe('FilterBar', () => {
  beforeEach(resetStore)

  it('renders the four filter dimensions with semantic tokens', () => {
    render(<FilterBar />)
    const bar = screen.getByTestId('filter-bar')
    expect(bar).toBeInTheDocument()
    // surface pin — same approach as Shell.theme.test.tsx so Group D
    // can't regress to hardcoded slate classes that don't flip with
    // dark mode.
    expect(bar.className).toMatch(/\bbg-surface\b|\bborder-border-card\b/)
    expect(bar.className).not.toMatch(/\bbg-white\b/)

    expect(screen.getByTestId('filter-date-from')).toBeInTheDocument()
    expect(screen.getByTestId('filter-date-to')).toBeInTheDocument()
    expect(screen.getByTestId('filter-group-trigger')).toBeInTheDocument()
    // TLP region is a fieldset/legend pair — pin its presence
    expect(screen.getByTestId('filter-tlp')).toBeInTheDocument()
    expect(screen.getByTestId('filter-clear')).toBeInTheDocument()
  })

  it('typing in date inputs writes ISO strings to the store', async () => {
    const user = userEvent.setup()
    render(<FilterBar />)

    const from = screen.getByTestId('filter-date-from') as HTMLInputElement
    const to = screen.getByTestId('filter-date-to') as HTMLInputElement

    await user.type(from, '2026-01-01')
    expect(useFilterStore.getState().dateFrom).toBe('2026-01-01')

    await user.type(to, '2026-04-18')
    expect(useFilterStore.getState().dateTo).toBe('2026-04-18')
  })

  it('clicking a group checkbox toggles it in the store', async () => {
    const user = userEvent.setup()
    render(<FilterBar />)
    await user.click(screen.getByTestId('filter-group-trigger'))

    const firstOption = FILTER_GROUP_OPTIONS[0]
    const item = await screen.findByTestId(`filter-group-option-${firstOption.id}`)
    await user.click(item)
    expect(useFilterStore.getState().groupIds).toEqual([firstOption.id])

    await user.click(item)
    expect(useFilterStore.getState().groupIds).toEqual([])
  })

  it('clicking a TLP checkbox toggles it in the store', async () => {
    const user = userEvent.setup()
    render(<FilterBar />)
    const amber = screen.getByTestId('filter-tlp-AMBER')
    await user.click(amber)
    expect(useFilterStore.getState().tlpLevels).toEqual(['AMBER'])
    await user.click(amber)
    expect(useFilterStore.getState().tlpLevels).toEqual([])
  })

  it('clear button resets every dimension', async () => {
    const user = userEvent.setup()
    useFilterStore.setState({
      dateFrom: '2026-01-01',
      dateTo: '2026-04-18',
      groupIds: [FILTER_GROUP_OPTIONS[0].id],
      tlpLevels: ['AMBER', 'GREEN'],
    })
    render(<FilterBar />)
    await user.click(screen.getByTestId('filter-clear'))

    const state = useFilterStore.getState()
    expect(state.dateFrom).toBeNull()
    expect(state.dateTo).toBeNull()
    expect(state.groupIds).toEqual([])
    expect(state.tlpLevels).toEqual([])
  })

  it('reflects pre-existing store state on mount (controlled inputs)', () => {
    useFilterStore.setState({
      dateFrom: '2026-01-01',
      dateTo: '2026-04-18',
      groupIds: [FILTER_GROUP_OPTIONS[0].id],
      tlpLevels: ['WHITE'],
    })
    render(<FilterBar />)
    const from = screen.getByTestId('filter-date-from') as HTMLInputElement
    const to = screen.getByTestId('filter-date-to') as HTMLInputElement
    expect(from.value).toBe('2026-01-01')
    expect(to.value).toBe('2026-04-18')

    const tlpWhite = screen.getByTestId('filter-tlp-WHITE') as HTMLInputElement
    const tlpGreen = screen.getByTestId('filter-tlp-GREEN') as HTMLInputElement
    expect(tlpWhite.checked).toBe(true)
    expect(tlpGreen.checked).toBe(false)
  })
})

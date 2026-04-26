import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useReportsViewModeStore } from '../../stores/reportsViewMode'
import { ReportsViewModeToggle } from '../ReportsViewModeToggle'

function reset(): void {
  window.localStorage.clear()
  useReportsViewModeStore.setState({ mode: 'list' })
}

beforeEach(reset)
afterEach(reset)

describe('ReportsViewModeToggle', () => {
  it('renders with list-mode aria pointing to timeline as the next action', () => {
    render(<ReportsViewModeToggle />)
    const btn = screen.getByTestId('reports-view-mode-toggle')
    expect(btn).toHaveAttribute('aria-label', 'Switch to timeline view')
    expect(btn).toHaveAttribute('title', 'Switch to timeline view')
    expect(btn).toHaveAttribute('data-view-mode', 'list')
  })

  it('shows timeline-mode aria after toggle', async () => {
    render(<ReportsViewModeToggle />)
    await userEvent.setup().click(
      screen.getByTestId('reports-view-mode-toggle'),
    )
    const btn = screen.getByTestId('reports-view-mode-toggle')
    expect(btn).toHaveAttribute('aria-label', 'Switch to list view')
    expect(btn).toHaveAttribute('data-view-mode', 'timeline')
  })

  it('click flips list ↔ timeline both directions', async () => {
    render(<ReportsViewModeToggle />)
    const user = userEvent.setup()
    expect(useReportsViewModeStore.getState().mode).toBe('list')
    await user.click(screen.getByTestId('reports-view-mode-toggle'))
    expect(useReportsViewModeStore.getState().mode).toBe('timeline')
    await user.click(screen.getByTestId('reports-view-mode-toggle'))
    expect(useReportsViewModeStore.getState().mode).toBe('list')
  })

  it('mounts with the persisted mode when store is pre-seeded', () => {
    useReportsViewModeStore.setState({ mode: 'timeline' })
    render(<ReportsViewModeToggle />)
    expect(
      screen.getByTestId('reports-view-mode-toggle'),
    ).toHaveAttribute('data-view-mode', 'timeline')
  })
})

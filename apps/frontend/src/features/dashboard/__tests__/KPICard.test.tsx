import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { KPICard } from '../KPICard'

describe('KPICard', () => {
  it('renders a skeleton + aria-busy in loading state', () => {
    render(<KPICard label="Total Reports" state="loading" />)
    const card = screen.getByTestId('kpi-card')
    expect(card.getAttribute('aria-busy')).toBe('true')
    // Skeleton-specific testid — never exposes a real value
    expect(screen.getByTestId('kpi-card-skeleton')).toBeInTheDocument()
    expect(screen.queryByTestId('kpi-card-value')).not.toBeInTheDocument()
  })

  it('renders value + subtext in populated state', () => {
    render(
      <KPICard
        label="Total Reports"
        value={1204}
        subtext="2024 peak"
        state="populated"
      />,
    )
    expect(screen.getByTestId('kpi-card-value')).toHaveTextContent('1,204')
    expect(screen.getByText('Total Reports')).toBeInTheDocument()
    expect(screen.getByText('2024 peak')).toBeInTheDocument()
  })

  it('renders placeholder dash + no subtext in empty state', () => {
    render(<KPICard label="Top Group" state="empty" />)
    expect(screen.getByTestId('kpi-card-value')).toHaveTextContent('—')
    expect(screen.queryByTestId('kpi-card-retry')).not.toBeInTheDocument()
  })

  it('renders retry button in error state and invokes onRetry on click', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    render(<KPICard label="Total Reports" state="error" onRetry={onRetry} />)

    const retry = screen.getByTestId('kpi-card-retry')
    await user.click(retry)
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('error state without onRetry still renders an error message', () => {
    render(<KPICard label="Total Reports" state="error" />)
    expect(screen.getByTestId('kpi-card-error-message')).toBeInTheDocument()
    // Retry is opt-in — cards lower in a strip reuse a shared retry
    expect(screen.queryByTestId('kpi-card-retry')).not.toBeInTheDocument()
  })

  it('uses semantic tokens on the outer surface (D4)', () => {
    render(<KPICard label="Total Reports" state="empty" />)
    const card = screen.getByTestId('kpi-card')
    expect(card.className).toMatch(/\bbg-surface\b/)
    expect(card.className).not.toMatch(/\bbg-white\b/)
  })

  it('formats numeric values with locale grouping', () => {
    render(<KPICard label="Total Reports" value={1234567} state="populated" />)
    // \u00A0 is some locales' thousand separator; we assert "1,234,567"
    // deterministically by passing en-US formatting internally.
    expect(screen.getByTestId('kpi-card-value')).toHaveTextContent('1,234,567')
  })
})

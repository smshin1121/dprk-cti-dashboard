import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../../lib/api'
import type { ReportItem } from '../../../lib/api/schemas'
import { ReportTimeline } from '../ReportTimeline'

const r1: ReportItem = {
  id: 1,
  title: 'Lazarus April leak',
  url: 'https://example.test/1',
  url_canonical: 'https://example.test/1',
  published: '2026-04-26',
  source_id: 1,
  source_name: 'Mandiant',
  lang: 'en',
  tlp: 'WHITE',
}
const r2: ReportItem = {
  ...r1,
  id: 2,
  title: 'APT38 wallet drain',
  url: 'https://example.test/2',
  source_name: 'Recorded Future',
  tlp: 'GREEN',
}
const r3: ReportItem = {
  ...r1,
  id: 3,
  title: 'Earlier-day report',
  url: 'https://example.test/3',
  published: '2026-04-25',
  source_name: 'Mandiant',
  tlp: null,
}

describe('ReportTimeline — render states', () => {
  it('renders skeleton in loading state', () => {
    render(<ReportTimeline rows={[]} state="loading" />)
    expect(
      screen.getByTestId('reports-timeline-skeleton'),
    ).toHaveAttribute('aria-busy', 'true')
  })

  it('renders empty card with positive no-row assertion', () => {
    render(<ReportTimeline rows={[]} state="empty" />)
    expect(screen.getByTestId('reports-timeline-empty')).toBeInTheDocument()
    expect(screen.queryByTestId('reports-timeline')).not.toBeInTheDocument()
  })

  it('renders error with retry button', async () => {
    const onRetry = vi.fn()
    render(<ReportTimeline rows={[]} state="error" onRetry={onRetry} />)
    expect(screen.getByTestId('reports-timeline-error')).toBeInTheDocument()
    await userEvent
      .setup()
      .click(screen.getByTestId('reports-timeline-retry'))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('renders 429-specific message on ApiError 429', () => {
    render(
      <ReportTimeline
        rows={[]}
        state="error"
        error={new ApiError(429, 'rate limited')}
      />,
    )
    expect(
      screen.getByText(/Too many requests/),
    ).toBeInTheDocument()
  })
})

describe('ReportTimeline — populated', () => {
  it('groups adjacent same-day rows under one day header', () => {
    render(<ReportTimeline rows={[r1, r2, r3]} state="populated" />)
    // 2 day groups (r1+r2 share 2026-04-26, r3 alone on 2026-04-25)
    expect(
      screen.getByTestId('reports-timeline-day-2026-04-26'),
    ).toBeInTheDocument()
    expect(
      screen.getByTestId('reports-timeline-day-2026-04-25'),
    ).toBeInTheDocument()
  })

  it('preserves BE order both across groups and within a group', () => {
    render(<ReportTimeline rows={[r1, r2, r3]} state="populated" />)
    const items = screen.getAllByTestId(/^reports-timeline-item-/)
    // BE order: r1 (id=1, day=04-26) → r2 (id=2, day=04-26) → r3 (id=3, day=04-25)
    expect(items.map((el) => el.getAttribute('data-testid'))).toEqual([
      'reports-timeline-item-1',
      'reports-timeline-item-2',
      'reports-timeline-item-3',
    ])
  })

  it('links the title externally with rel=noreferrer', () => {
    render(<ReportTimeline rows={[r1]} state="populated" />)
    const link = screen.getByText('Lazarus April leak') as HTMLAnchorElement
    expect(link.tagName).toBe('A')
    expect(link.getAttribute('href')).toBe('https://example.test/1')
    expect(link.getAttribute('rel')).toContain('noreferrer')
    expect(link.getAttribute('target')).toBe('_blank')
  })

  it('renders source + tlp meta with em-dash for null tlp', () => {
    render(<ReportTimeline rows={[r3]} state="populated" />)
    expect(screen.getByTestId('reports-timeline-source-3')).toHaveTextContent(
      'Mandiant',
    )
    expect(screen.getByTestId('reports-timeline-tlp-3')).toHaveTextContent('—')
  })
})

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../../lib/api'
import { ListTable, type ListTableColumn } from '../ListTable'

interface Row {
  id: number
  name: string
}

const columns: readonly ListTableColumn<Row>[] = [
  { header: 'ID', render: (r) => r.id },
  { header: 'Name', render: (r) => r.name },
] as const

describe('ListTable', () => {
  it('renders aria-busy skeleton in loading state (no real row data)', () => {
    render(
      <ListTable
        caption="actors"
        columns={columns}
        rows={[]}
        state="loading"
        getRowKey={(r) => r.id}
      />,
    )
    const skeleton = screen.getByTestId('list-table-loading')
    expect(skeleton.getAttribute('aria-busy')).toBe('true')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders an accessible <table> with caption + rows in populated state', () => {
    const rows: Row[] = [
      { id: 3, name: 'Lazarus Group' },
      { id: 5, name: 'Kimsuky' },
    ]
    render(
      <ListTable
        caption="Actor list"
        columns={columns}
        rows={rows}
        state="populated"
        getRowKey={(r) => r.id}
      />,
    )
    const table = screen.getByRole('table')
    expect(table).toBeInTheDocument()
    // Caption is sr-only but present for screen-readers
    expect(screen.getByText('Actor list')).toBeInTheDocument()
    expect(screen.getAllByTestId('list-table-row')).toHaveLength(2)
    expect(screen.getByText('Lazarus Group')).toBeInTheDocument()
    expect(screen.getByText('Kimsuky')).toBeInTheDocument()
  })

  it('renders "no rows" empty state when state=empty', () => {
    render(
      <ListTable
        caption="actors"
        columns={columns}
        rows={[]}
        state="empty"
        getRowKey={(r) => r.id}
      />,
    )
    expect(screen.getByTestId('list-table-empty')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('renders rate-limit specific message on 429', () => {
    render(
      <ListTable
        caption="actors"
        columns={columns}
        rows={[]}
        state="error"
        error={new ApiError(429, { error: 'rate_limit_exceeded' })}
        getRowKey={(r) => r.id}
      />,
    )
    expect(screen.getByTestId('list-table-error-rate-limit')).toBeInTheDocument()
    expect(screen.queryByTestId('list-table-error-generic')).not.toBeInTheDocument()
  })

  it('renders generic error message on non-429 error', () => {
    render(
      <ListTable
        caption="actors"
        columns={columns}
        rows={[]}
        state="error"
        error={new ApiError(500, null)}
        getRowKey={(r) => r.id}
      />,
    )
    expect(screen.getByTestId('list-table-error-generic')).toBeInTheDocument()
    expect(screen.queryByTestId('list-table-error-rate-limit')).not.toBeInTheDocument()
  })

  it('renders the retry button when onRetry is provided and invokes it on click', async () => {
    const onRetry = vi.fn()
    render(
      <ListTable
        caption="actors"
        columns={columns}
        rows={[]}
        state="error"
        error={new ApiError(500, null)}
        onRetry={onRetry}
        getRowKey={(r) => r.id}
      />,
    )
    await userEvent.setup().click(screen.getByTestId('list-table-retry'))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})

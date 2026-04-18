import { render, screen } from '@testing-library/react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import { useFilterStore } from '../../stores/filters'
import { Shell } from '../Shell'

function renderShell() {
  const router = createMemoryRouter(
    [
      {
        element: <Shell />,
        children: [
          { path: '/', element: <div data-testid="outlet-content" /> },
        ],
      },
    ],
    { initialEntries: ['/'] },
  )
  return render(<RouterProvider router={router} />)
}

function resetStore(): void {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
}

describe('Shell — FilterBar integration (plan D5)', () => {
  beforeEach(resetStore)

  it('mounts FilterBar inside the Shell layout', () => {
    renderShell()
    expect(screen.getByTestId('filter-bar')).toBeInTheDocument()
  })

  it('FilterBar sits above the main outlet, below the topbar', () => {
    renderShell()
    const topnav = screen.getByTestId('shell-topnav')
    const filterBar = screen.getByTestId('filter-bar')
    const main = screen.getByTestId('shell-main')

    // Document order: topbar → filter-bar → main. compareDocumentPosition
    // returns FOLLOWING (0x04) when the other node is after `this`.
    const FOLLOWING = Node.DOCUMENT_POSITION_FOLLOWING
    expect(topnav.compareDocumentPosition(filterBar) & FOLLOWING).toBeTruthy()
    expect(filterBar.compareDocumentPosition(main) & FOLLOWING).toBeTruthy()
  })
})

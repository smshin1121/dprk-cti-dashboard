import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { SimilarReports } from '../SimilarReports'

afterEach(() => vi.restoreAllMocks())

describe('SimilarReports — Phase 3 stub', () => {
  it('renders the static placeholder + phase note (no data plumbing)', () => {
    render(<SimilarReports />)
    expect(screen.getByTestId('similar-reports-stub')).toBeInTheDocument()
    expect(screen.getByTestId('similar-reports-placeholder')).toBeInTheDocument()
    expect(screen.getByTestId('similar-reports-phase-note')).toBeInTheDocument()
  })

  it('marks itself as a Phase 3 stub in HTML attributes (upgrade hook)', () => {
    render(<SimilarReports />)
    const root = screen.getByTestId('similar-reports-stub')
    // `data-phase-status` flips from "stub" to "live" when Phase 3
    // detail endpoints land — regression tests can assert on it.
    expect(root).toHaveAttribute('data-phase-status', 'stub')
    expect(root).toHaveAttribute('data-phase', 'phase-3')
  })

  it('does not call fetch (zero data plumbing)', async () => {
    const spy = vi.spyOn(global, 'fetch')
    render(<SimilarReports />)
    // Give React Query / effects a frame to fire anything queued.
    await waitFor(() => expect(true).toBe(true))
    expect(spy).not.toHaveBeenCalled()
  })
})

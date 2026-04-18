import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../lib/api'
import { RouteErrorBoundary } from '../RouteErrorBoundary'

// Mock useRouteError rather than driving a real loader throw.
// react-router's loader path creates an in-memory Request via
// undici's fetch, which clashes with jsdom's AbortSignal — the
// resulting unhandled rejection noise drowns out the actual
// assertions. Mocking useRouteError exercises the component's
// rendering logic directly, which is what this test cares about.
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  )
  return { ...actual, useRouteError: vi.fn() }
})

const useRouteErrorMock = (await import('react-router-dom'))
  .useRouteError as ReturnType<typeof vi.fn>

describe('RouteErrorBoundary', () => {
  it('renders inline card with ApiError status + detail.message', () => {
    useRouteErrorMock.mockReturnValue(new ApiError(503, { message: 'Storage down' }))
    render(<RouteErrorBoundary />)
    expect(screen.getByTestId('route-error-boundary')).toBeInTheDocument()
    expect(screen.getByText(/Request failed \(503\)/)).toBeInTheDocument()
    expect(screen.getByTestId('route-error-detail')).toHaveTextContent(
      'Storage down',
    )
    // D11 inline-retry lock — the affordance is present.
    expect(
      screen.getByRole('button', { name: /reload this section/i }),
    ).toBeInTheDocument()
  })

  it('renders Error.message for plain Error throws', () => {
    useRouteErrorMock.mockReturnValue(new Error('unexpected render failure'))
    render(<RouteErrorBoundary />)
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument()
    expect(screen.getByTestId('route-error-detail')).toHaveTextContent(
      'unexpected render failure',
    )
  })

  it('falls back to generic message for non-Error throws', () => {
    useRouteErrorMock.mockReturnValue('string throw')
    render(<RouteErrorBoundary />)
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument()
    expect(screen.queryByTestId('route-error-detail')).not.toBeInTheDocument()
  })

  it('handles ApiError without a detail.message field', () => {
    useRouteErrorMock.mockReturnValue(new ApiError(500, null))
    render(<RouteErrorBoundary />)
    expect(screen.getByText(/Request failed \(500\)/)).toBeInTheDocument()
    expect(screen.queryByTestId('route-error-detail')).not.toBeInTheDocument()
  })
})

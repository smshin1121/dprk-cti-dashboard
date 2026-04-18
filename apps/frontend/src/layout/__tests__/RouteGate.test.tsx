import { render, screen } from '@testing-library/react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuthStore } from '../../stores/auth'
import { RouteGate } from '../RouteGate'

// Mock useAuth so each test drives its own auth state directly,
// independent of useMe / react-query / fetch. RouteGate is a pure
// consumer of useAuth — isolating it here lets the gate's four
// branches get one test each.
vi.mock('../../features/auth/useAuth', () => ({
  useAuth: vi.fn(),
}))

const useAuthMock = (await import('../../features/auth/useAuth')).useAuth as ReturnType<
  typeof vi.fn
>

function renderGateAt(initialPath: string) {
  // /login is a sibling of the gate, not a child — same shape as
  // the real buildRouter() tree. Putting /login under the gate
  // would infinite-loop: the gate's Navigate fires → /login child
  // re-enters the gate → Navigate again → ad infinitum.
  const router = createMemoryRouter(
    [
      { path: '/login', element: <div data-testid="login">login</div> },
      {
        element: <RouteGate />,
        children: [
          // Catch-all for protected content. Matches /dashboard,
          // /reports?tag=..., /anything-else so the gate test can
          // drive the branch logic for every path without having
          // to enumerate each route.
          {
            path: '*',
            element: <div data-testid="protected">protected</div>,
          },
        ],
      },
    ],
    { initialEntries: [initialPath] },
  )
  return render(<RouterProvider router={router} />)
}

describe('RouteGate', () => {
  beforeEach(() => {
    useAuthStore.setState({ postLoginRedirect: null })
  })

  it('renders RouteSkeleton while auth status is loading', () => {
    useAuthMock.mockReturnValue({
      user: null,
      status: 'loading',
      hasEverBeenAuthenticated: false,
    })
    renderGateAt('/dashboard')
    expect(screen.getByTestId('route-skeleton')).toBeInTheDocument()
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument()
    expect(screen.queryByTestId('login')).not.toBeInTheDocument()
  })

  it('renders Outlet when authenticated', () => {
    useAuthMock.mockReturnValue({
      user: { sub: 'abc', email: 'a', name: null, roles: ['analyst'] },
      status: 'authenticated',
      hasEverBeenAuthenticated: true,
    })
    renderGateAt('/dashboard')
    expect(screen.getByTestId('protected')).toBeInTheDocument()
  })

  it('redirects to /login on session expiry (unauth + hasEverBeenAuthenticated=true)', () => {
    useAuthMock.mockReturnValue({
      user: null,
      status: 'unauthenticated',
      hasEverBeenAuthenticated: true,
    })
    renderGateAt('/dashboard')
    expect(screen.getByTestId('login')).toBeInTheDocument()
    expect(screen.queryByTestId('route-gate-boot-error')).not.toBeInTheDocument()
  })

  it('shows boot-error card on first-boot unauth (D2.A.2 loop guard)', () => {
    useAuthMock.mockReturnValue({
      user: null,
      status: 'unauthenticated',
      hasEverBeenAuthenticated: false,
    })
    renderGateAt('/dashboard')
    expect(screen.getByTestId('route-gate-boot-error')).toBeInTheDocument()
    // Does NOT redirect — that would infinite-loop (gate fires again
    // on /login which ALSO fails the me check).
    expect(screen.queryByTestId('login')).not.toBeInTheDocument()
  })

  it('captures the attempted path into postLoginRedirect before redirecting', () => {
    useAuthMock.mockReturnValue({
      user: null,
      status: 'unauthenticated',
      hasEverBeenAuthenticated: true,
    })
    renderGateAt('/reports?tag=ransomware')
    expect(useAuthStore.getState().postLoginRedirect).toBe(
      '/reports?tag=ransomware',
    )
  })

  it('does NOT capture /login as the postLoginRedirect (would self-bounce)', () => {
    useAuthMock.mockReturnValue({
      user: null,
      status: 'unauthenticated',
      hasEverBeenAuthenticated: true,
    })
    // Arrange: the gate mounts at /login somehow (e.g. a stale
    // guarded route config). Store must remain null.
    renderGateAt('/login')
    expect(useAuthStore.getState().postLoginRedirect).toBeNull()
  })
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { useAuthStore } from '../../stores/auth'
import { buildRouter } from '../router'

/**
 * Full-tree mounting tests using the real buildRouter() config
 * driven by createMemoryRouter. `useAuth` is mocked so each test
 * drives its own auth state — the RouteGate's four branches are
 * separately exercised in RouteGate.test.tsx; this file focuses
 * on whether the protected routes actually mount under the gate.
 */

vi.mock('../../features/auth/useAuth', () => ({
  useAuth: vi.fn(),
}))

const useAuthMock = (await import('../../features/auth/useAuth')).useAuth as ReturnType<
  typeof vi.fn
>

function QCWrapper({
  children,
  client,
}: {
  children: ReactNode
  client: QueryClient
}) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function renderRouterAt(initialPath: string, client?: QueryClient) {
  const qc = client ?? createQueryClient()
  const router = buildRouter((routes) =>
    createMemoryRouter(routes, { initialEntries: [initialPath] }),
  )
  return render(
    <QCWrapper client={qc}>
      <RouterProvider router={router} />
    </QCWrapper>,
  )
}

function mockAuthed() {
  useAuthMock.mockReturnValue({
    user: { sub: 'abc', email: 'a@test', name: null, roles: ['analyst'] },
    status: 'authenticated',
    hasEverBeenAuthenticated: true,
  })
}

describe('Router tree — protected route mounts', () => {
  beforeEach(() => {
    useAuthStore.setState({ postLoginRedirect: null })
  })

  it.each([
    ['/dashboard', 'dashboard-page', /Dashboard/],
    ['/actors', 'actors-page', /Actors/],
    ['/reports', 'reports-page', /Reports/],
    ['/incidents', 'incidents-page', /Incidents/],
  ])(
    'authenticated user lands on %s and its page mounts inside the Shell',
    async (path, testId, heading) => {
      mockAuthed()
      renderRouterAt(path)
      expect(await screen.findByTestId(testId)).toBeInTheDocument()
      expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument()
      // Shell must also be present — D11 nav stays interactive during
      // content changes.
      expect(screen.getByTestId('shell-topnav')).toBeInTheDocument()
    },
  )

  it('root "/" redirects to /dashboard when authenticated', async () => {
    mockAuthed()
    renderRouterAt('/')
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument()
  })

  it('unknown protected path renders the inline 404, keeping the Shell', async () => {
    mockAuthed()
    renderRouterAt('/does-not-exist')
    expect(await screen.findByText(/Not found/i)).toBeInTheDocument()
    expect(screen.getByTestId('shell-topnav')).toBeInTheDocument()
  })
})

describe('Router tree — unauthenticated redirect flow', () => {
  beforeEach(() => {
    useAuthStore.setState({ postLoginRedirect: null })
  })

  it('session-expiry: captures intent path and redirects /reports → /login', async () => {
    useAuthMock.mockReturnValue({
      user: null,
      status: 'unauthenticated',
      hasEverBeenAuthenticated: true,
    })
    renderRouterAt('/reports?tag=ransomware')
    // Login page mounts
    expect(await screen.findByTestId('login-page')).toBeInTheDocument()
    // Login page snapshots the captured target into the Sign-in
    // link's data attribute and immediately clears the store so a
    // later /login visit doesn't resurrect a stale intent. Asserting
    // on the link's target is the correct surface for this flow —
    // the store is an implementation detail of the round-trip, the
    // link's target is the observable contract to the backend.
    const link = await screen.findByTestId('login-submit')
    expect(link.getAttribute('data-login-target')).toBe(
      '/reports?tag=ransomware',
    )
    // Store cleared post-consumption (plan D10 minimal-state lock —
    // stale intents must not accumulate).
    await waitFor(() =>
      expect(useAuthStore.getState().postLoginRedirect).toBeNull(),
    )
  })

  it('first-boot config failure: boot-error card at /dashboard without redirect', async () => {
    useAuthMock.mockReturnValue({
      user: null,
      status: 'unauthenticated',
      hasEverBeenAuthenticated: false,
    })
    renderRouterAt('/dashboard')
    expect(
      await screen.findByTestId('route-gate-boot-error'),
    ).toBeInTheDocument()
    // No redirect — D2.A.2 lock. Login page must NOT mount (would
    // just loop, /login page itself doesn't help if the API is
    // unreachable).
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
  })

  it('/login is public — renders even when unauthenticated', async () => {
    useAuthMock.mockReturnValue({
      user: null,
      status: 'unauthenticated',
      hasEverBeenAuthenticated: false,
    })
    renderRouterAt('/login')
    expect(await screen.findByTestId('login-page')).toBeInTheDocument()
  })

  it('loading state renders the skeleton, never the login page or content', () => {
    useAuthMock.mockReturnValue({
      user: null,
      status: 'loading',
      hasEverBeenAuthenticated: false,
    })
    renderRouterAt('/dashboard')
    expect(screen.getByTestId('route-skeleton')).toBeInTheDocument()
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument()
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument()
  })
})

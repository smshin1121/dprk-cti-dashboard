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
import { LoginPage } from '../LoginPage'

function Wrap({
  client,
  children,
}: {
  client: QueryClient
  children: ReactNode
}) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function renderLoginWithRouter(opts: {
  initialPath?: string
  client?: QueryClient
} = {}) {
  const client = opts.client ?? createQueryClient()
  const router = createMemoryRouter(
    [
      { path: '/login', element: <LoginPage /> },
      {
        path: '/dashboard',
        element: <div data-testid="dashboard-landing" />,
      },
      {
        path: '/reports',
        element: <div data-testid="reports-landing" />,
      },
    ],
    { initialEntries: [opts.initialPath ?? '/login'] },
  )
  return render(
    <Wrap client={client}>
      <RouterProvider router={router} />
    </Wrap>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    useAuthStore.setState({ postLoginRedirect: null })
    // Prevent the inner useMe from actually hitting the network.
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'no session' }), { status: 401 }),
    )
  })

  it('renders the sign-in affordance when unauthenticated', async () => {
    renderLoginWithRouter()
    const link = await screen.findByTestId('login-submit')
    expect(link).toBeInTheDocument()
    // Default target is /dashboard when no postLoginRedirect is set.
    expect(link.getAttribute('data-login-target')).toBe('/dashboard')
  })

  it('encodes postLoginRedirect into the sign-in href', async () => {
    useAuthStore.setState({ postLoginRedirect: '/reports?tag=ransomware' })
    renderLoginWithRouter()
    const link = await screen.findByTestId('login-submit')
    expect(link.getAttribute('data-login-target')).toBe(
      '/reports?tag=ransomware',
    )
    // The href encodes the absolute URL form.
    const href = link.getAttribute('href') ?? ''
    expect(href).toContain('/api/v1/auth/login?redirect=')
    expect(href).toContain(encodeURIComponent('/reports?tag=ransomware'))
  })

  it('clears postLoginRedirect from the store on mount to prevent stale reuse', async () => {
    useAuthStore.setState({ postLoginRedirect: '/reports' })
    renderLoginWithRouter()
    await screen.findByTestId('login-submit')
    expect(useAuthStore.getState().postLoginRedirect).toBeNull()
  })

  it('snapshots the target before clearing — the sign-in link stays usable', async () => {
    useAuthStore.setState({ postLoginRedirect: '/incidents' })
    renderLoginWithRouter()
    const link = await screen.findByTestId('login-submit')
    // postLoginRedirect cleared, but target snapshotted on mount.
    expect(useAuthStore.getState().postLoginRedirect).toBeNull()
    expect(link.getAttribute('data-login-target')).toBe('/incidents')
  })

  it('redirects away when user is already authenticated', async () => {
    const client = createQueryClient()
    client.setQueryData(['me'], {
      sub: 'abc',
      email: 'a',
      name: null,
      roles: ['analyst'],
    })
    useAuthStore.setState({ postLoginRedirect: '/reports' })
    renderLoginWithRouter({ client })
    // LoginPage Navigate's to the snapshotted target (reports).
    await waitFor(() =>
      expect(screen.getByTestId('reports-landing')).toBeInTheDocument(),
    )
  })
})

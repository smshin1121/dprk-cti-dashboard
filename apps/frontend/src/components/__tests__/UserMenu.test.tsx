import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createQueryClient } from '../../lib/queryClient'
import { UserMenu } from '../UserMenu'

const ME_BODY = {
  sub: 'abc-123',
  email: 'analyst@dprk.test',
  name: 'Jane Analyst',
  roles: ['analyst'],
}

function renderUserMenu(locationCapture?: (path: string) => void) {
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: (
          <>
            <UserMenu />
            <LocationProbe onChange={locationCapture} />
          </>
        ),
      },
      { path: '/login', element: <div data-testid="login-marker" /> },
    ],
    { initialEntries: ['/'] },
  )
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return { ...render(<RouterProvider router={router} />, { wrapper: Wrapper }), client }
}

function LocationProbe({
  onChange,
}: {
  onChange?: (path: string) => void
}): JSX.Element {
  const { useLocation } = require('react-router-dom') as typeof import('react-router-dom')
  const loc = useLocation()
  if (onChange) onChange(loc.pathname)
  return <span data-testid="location" data-path={loc.pathname} />
}

beforeEach(() => {
  window.localStorage.clear()
  vi.spyOn(global, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(ME_BODY), { status: 200 }),
  )
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('UserMenu', () => {
  it('trigger renders user identity affordance when authenticated', async () => {
    renderUserMenu()
    await waitFor(() =>
      expect(screen.getByTestId('user-menu-trigger')).toBeInTheDocument(),
    )
  })

  it('dropdown shows email + role badge + logout (no theme toggle after Ferrari L1)', async () => {
    const user = userEvent.setup()
    renderUserMenu()
    await waitFor(() =>
      expect(screen.getByTestId('user-menu-trigger')).toBeInTheDocument(),
    )

    await user.click(screen.getByTestId('user-menu-trigger'))
    // Email + role rendered from useAuth identity
    expect(await screen.findByTestId('user-menu-email')).toHaveTextContent(
      'analyst@dprk.test',
    )
    expect(screen.getByTestId('user-menu-role')).toHaveTextContent('analyst')
    // Theme toggle removed in Ferrari L1 (single dark canvas).
    expect(screen.queryByTestId('theme-toggle')).not.toBeInTheDocument()
    // Logout item present
    expect(screen.getByTestId('user-menu-logout')).toBeInTheDocument()
  })

  it('logout POSTs /auth/logout, clears cache, and navigates to /login', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch')
    // First call: /me in useAuth (already seeded via beforeEach mockResolvedValue)
    // We override per-call: first /me 200, then logout 204.
    fetchSpy.mockImplementation((input) => {
      const url = typeof input === 'string' ? input : input instanceof Request ? input.url : String(input)
      if (url.endsWith('/api/v1/auth/logout')) {
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(new Response(JSON.stringify(ME_BODY), { status: 200 }))
    })

    const user = userEvent.setup()
    const { client } = renderUserMenu()
    await waitFor(() => {
      expect(screen.getByTestId('user-menu-trigger')).toBeInTheDocument()
    })
    // Prime: queryClient has ['me'] cached after the bootstrap fetch.
    await waitFor(() => expect(client.getQueryData(['me'])).toEqual(ME_BODY))

    await user.click(screen.getByTestId('user-menu-trigger'))
    await user.click(await screen.findByTestId('user-menu-logout'))

    await waitFor(() => {
      const call = fetchSpy.mock.calls.find(([u]) => String(u).endsWith('/api/v1/auth/logout'))
      expect(call?.[1]?.method).toBe('POST')
    })

    // Cache cleared after logout success (useLogout.onSuccess)
    await waitFor(() => expect(client.getQueryData(['me'])).toBeUndefined())

    // Route navigated to /login — the login marker route renders.
    await waitFor(() =>
      expect(screen.getByTestId('login-marker')).toBeInTheDocument(),
    )
  })
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import i18n from 'i18next'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
} from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Side-effect bootstrap (Codex PR #33 r3 F1''): the /dashboard route
// assertion below uses the translated `Threat Overview` heading, so
// i18n must be initialized in this isolated test file. Without this
// import, behavior depends on whether another module previously
// pulled i18n into the cache (transitive) and on happy-dom's
// navigator.language default — fragile across test orderings.
import '../../i18n'
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
  beforeEach(async () => {
    useAuthStore.setState({ postLoginRedirect: null })
    // Pin locale to EN so the /dashboard heading regex below resolves
    // deterministically regardless of test order or environment-
    // detected navigator.language. Codex PR #33 r3 F1'' fold.
    await i18n.changeLanguage('en')
  })

  it.each([
    // PR 2 T9 relayout: dashboard-heading-row's <h1> reads "Threat
    // Overview" in EN locale (per plan L11 / DESIGN.md ## Dashboard
    // Workspace Pattern). The old sr-only "Dashboard" heading was
    // removed. Locale pinned to EN in beforeEach above.
    ['/dashboard', 'dashboard-page', /Threat Overview/i],
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

  // PR-B T10 r1 fold (Codex CRITICAL). The /analytics/correlation
  // route mounts under <Shell>, which runs `useFilterUrlSync`. The
  // global URL sync emits a search string built from the filter
  // store's keys ONLY (date_from / date_to / group_id / view / tab)
  // — without the route-scope short-circuit added in this fold, a
  // deep link like /analytics/correlation?x=A&y=B&method=spearman
  // would survive the initial paint but get stripped by the global
  // sync's first non-mount emit (filter store updates from the
  // hydrate effect would trigger emit; emit would write a URL that
  // loses x / y / method). This test pins the post-fold contract.
  it('correlation deep link survives Shell hydration — page-local URL state preserved', async () => {
    mockAuthed()
    // Mock fetch so the catalog and primary endpoints don't hit the
    // network. The page itself rendering populated isn't the point
    // — the URL preservation invariant is the test target.
    vi.spyOn(global, 'fetch').mockImplementation((input) => {
      const url = String(input)
      if (url.includes('/api/v1/analytics/correlation/series')) {
        return Promise.resolve(
          new Response(JSON.stringify({ series: [] }), { status: 200 }),
        )
      }
      return Promise.resolve(
        new Response(JSON.stringify({ detail: [] }), { status: 422 }),
      )
    })
    renderRouterAt(
      '/analytics/correlation?x=reports.total&y=incidents.total&method=spearman',
    )
    expect(await screen.findByTestId('correlation-page')).toBeInTheDocument()
    // Wait for the global URL sync's first non-mount emit to settle —
    // any effect flush after mount must NOT have stripped page-local
    // params. Inspect the in-memory router's location instead of
    // `window.location` because createMemoryRouter writes there.
    await waitFor(() => {
      const probe = screen
        .getByTestId('correlation-page')
        .closest('[data-page-class="analyst-workspace"]')
      expect(probe).not.toBeNull()
    })
    // The CorrelationPage's own initial render runs `readUrlState`
    // off the router-tracked `location.search` value. If the global
    // sync had clobbered it, the page would have rendered the empty
    // branch (no x / y means `correlation-empty` testid). Asserting
    // that the populated / loading / error branch shows up — i.e.
    // anything but `correlation-empty` — proves x / y survived.
    expect(screen.queryByTestId('correlation-empty')).not.toBeInTheDocument()
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

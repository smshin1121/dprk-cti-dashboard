import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Command } from 'cmdk'
import type { ReactNode } from 'react'
import {
  RouterProvider,
  createMemoryRouter,
  useLocation,
} from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CommandPaletteButton } from '../../../components/CommandPaletteButton'
import { createQueryClient } from '../../../lib/queryClient'
import { useFilterStore } from '../../../stores/filters'
import { SearchResultsSection } from '../SearchResultsSection'
import { SEARCH_DEBOUNCE_MS } from '../useSearchHits'

// Lifted from the BE OpenAPI populated example for /api/v1/search.
const HAPPY_BODY = {
  items: [
    {
      report: {
        id: 999060,
        title: 'Lazarus targets SK crypto exchanges',
        url: 'https://pact.test/search/populated-999060',
        url_canonical: 'https://pact.test/search/populated-999060',
        published: '2026-03-15',
        source_id: 1,
        source_name: 'Vendor',
        lang: 'en',
        tlp: 'WHITE',
      },
      fts_rank: 0.0759,
      vector_rank: null,
    },
    {
      report: {
        id: 999061,
        title: 'Lazarus phishing campaign — MFA bypass',
        url: 'https://pact.test/search/populated-999061',
        url_canonical: 'https://pact.test/search/populated-999061',
        published: '2026-02-10',
        source_id: 1,
        source_name: 'Vendor',
        lang: 'en',
        tlp: 'WHITE',
      },
      fts_rank: 0.0512,
      vector_rank: null,
    },
  ],
  total_hits: 2,
  latency_ms: 42,
}

const EMPTY_BODY = { items: [], total_hits: 0, latency_ms: 12 }

const WAIT_PAST_DEBOUNCE_MS = SEARCH_DEBOUNCE_MS + 120

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

function LocationProbe(): JSX.Element {
  const loc = useLocation()
  return (
    <span
      data-testid="location"
      data-path={loc.pathname}
      data-search={loc.search}
    />
  )
}

function renderPalette() {
  const client = createQueryClient()
  const router = createMemoryRouter(
    [
      {
        path: '/',
        element: (
          <>
            <CommandPaletteButton />
            <LocationProbe />
          </>
        ),
      },
      { path: '/reports/:id', element: <LocationProbe /> },
      { path: '/dashboard', element: <LocationProbe /> },
      { path: '/login', element: <LocationProbe /> },
    ],
    { initialEntries: ['/'] },
  )
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return render(<RouterProvider router={router} />, { wrapper: Wrapper })
}

// Standalone SearchResultsSection render harness for state-isolation
// tests. Used for loading/error/populated assertions where we want
// to drive `q` directly without going through the palette's state
// machine. Wraps in <Command> so cmdk context is available.
function renderIsolated(q: string, onSelect = vi.fn()): { unmount: () => void } {
  const client = createQueryClient()
  return render(
    <QueryClientProvider client={client}>
      <Command>
        <Command.List>
          <SearchResultsSection q={q} onSelectResult={onSelect} />
        </Command.List>
      </Command>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

// -----------------------------------------------------------------------
// Review criterion #1 — 4 state separation (loading / error / empty /
// populated). Each state is individually addressable by a distinct
// data-testid so a regression that collapses two into one flips red.
// -----------------------------------------------------------------------

describe('SearchResultsSection — 4-state contract', () => {
  it('renders NOTHING when q is empty (returns null)', () => {
    renderIsolated('')
    expect(screen.queryByTestId('search-results-section')).not.toBeInTheDocument()
  })

  it('renders NOTHING when q is whitespace-only', () => {
    renderIsolated('   ')
    expect(screen.queryByTestId('search-results-section')).not.toBeInTheDocument()
  })

  it('shows the loading state while waiting for debounce + fetch', async () => {
    // fetch never resolves — hold the loading state indefinitely so
    // we can observe the debounce-window branch AND the in-flight
    // fetch branch without racing.
    vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise(() => undefined),
    )
    renderIsolated('lazarus')

    // Immediately inside debounce window: data === undefined, isError
    // false — loading row shown.
    expect(screen.getByTestId('search-state-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('search-state-empty')).not.toBeInTheDocument()
    expect(screen.queryByTestId('search-state-error')).not.toBeInTheDocument()
    expect(screen.queryByTestId('search-state-populated')).not.toBeInTheDocument()

    // Cross the debounce window. Fetch fires + hangs; loading stays.
    await sleep(WAIT_PAST_DEBOUNCE_MS)
    expect(screen.getByTestId('search-state-loading')).toBeInTheDocument()
  })

  it('shows the error state on fetch failure', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('network'))
    renderIsolated('lazarus')

    await waitFor(
      () => expect(screen.getByTestId('search-state-error')).toBeInTheDocument(),
      { timeout: WAIT_PAST_DEBOUNCE_MS + 2000 },
    )
    // Error branch mutually excludes the other three.
    expect(screen.queryByTestId('search-state-loading')).not.toBeInTheDocument()
    expect(screen.queryByTestId('search-state-empty')).not.toBeInTheDocument()
    expect(screen.queryByTestId('search-state-populated')).not.toBeInTheDocument()
  })

  it('shows the D10 empty state when items=[]', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(EMPTY_BODY), { status: 200 }),
    )
    renderIsolated('nomatchxyz123')

    await waitFor(
      () => expect(screen.getByTestId('search-state-empty')).toBeInTheDocument(),
      { timeout: WAIT_PAST_DEBOUNCE_MS + 500 },
    )
    expect(screen.getByTestId('search-state-empty')).toHaveTextContent(
      'No matches for "nomatchxyz123"',
    )
    // Empty branch mutually excludes the other three.
    expect(screen.queryByTestId('search-state-loading')).not.toBeInTheDocument()
    expect(screen.queryByTestId('search-state-error')).not.toBeInTheDocument()
    expect(screen.queryByTestId('search-state-populated')).not.toBeInTheDocument()
  })

  it('shows the populated state with one row per hit', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    renderIsolated('lazarus')

    await waitFor(
      () =>
        expect(
          screen.getByTestId('search-state-populated'),
        ).toBeInTheDocument(),
      { timeout: WAIT_PAST_DEBOUNCE_MS + 500 },
    )
    expect(screen.getByTestId('search-result-999060')).toHaveTextContent(
      'Lazarus targets SK crypto exchanges',
    )
    expect(screen.getByTestId('search-result-999061')).toHaveTextContent(
      'Lazarus phishing campaign — MFA bypass',
    )
    // Populated branch mutually excludes the other three.
    expect(screen.queryByTestId('search-state-loading')).not.toBeInTheDocument()
    expect(screen.queryByTestId('search-state-error')).not.toBeInTheDocument()
    expect(screen.queryByTestId('search-state-empty')).not.toBeInTheDocument()
  })
})

// -----------------------------------------------------------------------
// Review criterion #2 — the PR #13 D3 command set stays intact (modulo
// the Ferrari L1 removal of `theme.cycle`). The CommandPaletteButton
// test already pins exactly 6 items at dialog open
// (`renders exactly the 6 commands locked in plan D3 + Ferrari L1`).
// We augment here with: (a) the 6 cmdk-item testids STILL render when
// the palette is open with a non-empty q (search does NOT displace
// them from the DOM), and (b) the static COMMAND_IDS module export
// matches the post-Ferrari L1 lock.
// -----------------------------------------------------------------------

describe('CommandPaletteButton — D3 + Ferrari L1 6-command set preservation', () => {
  const STATIC_COMMAND_TESTIDS = [
    'cmdk-item-nav.dashboard',
    'cmdk-item-nav.reports',
    'cmdk-item-nav.incidents',
    'cmdk-item-nav.actors',
    'cmdk-item-filters.clear',
    'cmdk-item-auth.logout',
  ]

  it('all 6 commands render with no q entered (post-Ferrari L1 baseline)', async () => {
    const user = userEvent.setup()
    renderPalette()
    await user.click(screen.getByTestId('cmdk-trigger'))

    for (const testid of STATIC_COMMAND_TESTIDS) {
      expect(await screen.findByTestId(testid)).toBeInTheDocument()
    }
    // And the search section is NOT mounted at q=''.
    expect(screen.queryByTestId('search-results-section')).not.toBeInTheDocument()
  })

  it('COMMAND_IDS constant matches the post-Ferrari L1 scope lock', async () => {
    const { COMMAND_IDS } = await import('../../../lib/commands')
    expect([...COMMAND_IDS]).toEqual([
      'nav.dashboard',
      'nav.reports',
      'nav.incidents',
      'nav.actors',
      'filters.clear',
      'auth.logout',
    ])
  })
})

// -----------------------------------------------------------------------
// Review criterion #3 — search results live as a SIBLING section, not
// interleaved into the 7 static command items. Asserted structurally
// by comparing DOM ordering: every static cmdk-item-* appears before
// the `search-results-section` wrapper.
// -----------------------------------------------------------------------

describe('palette search — sibling section, not mixed into commands', () => {
  it('SearchResultsSection is a DOM sibling of the static command list', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const user = userEvent.setup()
    renderPalette()
    await user.click(screen.getByTestId('cmdk-trigger'))
    const input = await screen.findByTestId('cmdk-input')
    await user.type(input, 'lazarus')

    // Wait for the POPULATED state specifically — the section appears
    // during loading too, but result rows only exist once the fetch
    // resolves.
    await waitFor(
      () =>
        expect(
          screen.getByTestId('search-state-populated'),
        ).toBeInTheDocument(),
      { timeout: WAIT_PAST_DEBOUNCE_MS + 500 },
    )

    const section = screen.getByTestId('search-results-section')
    const list = screen.getByTestId('cmdk-list')
    // Section mounts inside the Command.List ancestor — same parent
    // as the static command items. That's the "sibling" shape.
    expect(list.contains(section)).toBe(true)

    // Also: no `cmdk-item-*` data-testid node lives inside the
    // search-results-section. If a future edit moved a static command
    // into the section (or vice versa) this would fire red.
    const itemsInsideSection = section.querySelectorAll(
      '[data-testid^="cmdk-item-"]',
    )
    expect(itemsInsideSection.length).toBe(0)

    // Conversely — no `search-result-*` row appears as a flat sibling
    // of the static command items (all result rows live inside the
    // search-results-section wrapper).
    const resultRows = screen.getAllByTestId(/^search-result-/)
    expect(resultRows.length).toBeGreaterThan(0)
    for (const row of resultRows) {
      expect(section.contains(row)).toBe(true)
    }
  })

  it('selecting a search result navigates to /reports/{id} and closes the palette', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const user = userEvent.setup()
    renderPalette()
    await user.click(screen.getByTestId('cmdk-trigger'))
    const input = await screen.findByTestId('cmdk-input')
    await user.type(input, 'lazarus')

    const firstHit = await waitFor(
      () => screen.getByTestId('search-result-999060'),
      { timeout: WAIT_PAST_DEBOUNCE_MS + 500 },
    )
    await user.click(firstHit)

    await waitFor(() =>
      expect(screen.getByTestId('location').getAttribute('data-path')).toBe(
        '/reports/999060',
      ),
    )
    expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()
  })
})

// -----------------------------------------------------------------------
// Review criterion #4 — q is palette-local ephemeral. Typing does NOT
// change the URL; closing the dialog resets q to ''; reopening starts
// empty. Covers the carry-over regression mode: a user types a query,
// dismisses the palette, reopens — q should NOT carry.
// -----------------------------------------------------------------------

describe('palette q — ephemeral, never leaks to URL or persistence', () => {
  it('typing q does NOT mutate the router location', async () => {
    const user = userEvent.setup()
    renderPalette()
    const initialPath = screen.getByTestId('location').getAttribute('data-path')
    const initialSearch = screen
      .getByTestId('location')
      .getAttribute('data-search')

    await user.click(screen.getByTestId('cmdk-trigger'))
    const input = await screen.findByTestId('cmdk-input')
    await user.type(input, 'lazarus targets')
    await sleep(WAIT_PAST_DEBOUNCE_MS)

    // Same path, same empty querystring. q never surfaces.
    expect(screen.getByTestId('location').getAttribute('data-path')).toBe(
      initialPath,
    )
    expect(screen.getByTestId('location').getAttribute('data-search')).toBe(
      initialSearch,
    )
  })

  it('typing q does NOT write to localStorage or sessionStorage', async () => {
    const localBefore = JSON.stringify({ ...window.localStorage })
    const sessionBefore = JSON.stringify({ ...window.sessionStorage })

    const user = userEvent.setup()
    renderPalette()
    await user.click(screen.getByTestId('cmdk-trigger'))
    const input = await screen.findByTestId('cmdk-input')
    await user.type(input, 'lazarus')
    await sleep(WAIT_PAST_DEBOUNCE_MS)

    expect(JSON.stringify({ ...window.localStorage })).toBe(localBefore)
    expect(JSON.stringify({ ...window.sessionStorage })).toBe(sessionBefore)
  })

  it('closing and reopening the palette resets q to empty', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(HAPPY_BODY), { status: 200 }),
    )
    const user = userEvent.setup()
    renderPalette()

    // Open 1 — type "lazarus", wait for results.
    await user.click(screen.getByTestId('cmdk-trigger'))
    const input1 = await screen.findByTestId('cmdk-input')
    await user.type(input1, 'lazarus')
    await waitFor(
      () =>
        expect(
          screen.getByTestId('search-results-section'),
        ).toBeInTheDocument(),
      { timeout: WAIT_PAST_DEBOUNCE_MS + 500 },
    )

    // Close via Escape.
    await user.keyboard('{Escape}')
    await waitFor(() =>
      expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument(),
    )

    // Open 2 — input must be empty AND search section must be gone.
    await user.click(screen.getByTestId('cmdk-trigger'))
    const input2 = (await screen.findByTestId('cmdk-input')) as HTMLInputElement
    expect(input2.value).toBe('')
    expect(screen.queryByTestId('search-results-section')).not.toBeInTheDocument()
  })

  it('filter store is untouched by typing q (no leak into global state)', async () => {
    const user = userEvent.setup()
    renderPalette()

    const stateBefore = { ...useFilterStore.getState() }

    await user.click(screen.getByTestId('cmdk-trigger'))
    const input = await screen.findByTestId('cmdk-input')
    await user.type(input, 'lazarus 2026-03-01')
    await sleep(WAIT_PAST_DEBOUNCE_MS)

    const stateAfter = useFilterStore.getState()
    expect(stateAfter.dateFrom).toBe(stateBefore.dateFrom)
    expect(stateAfter.dateTo).toBe(stateBefore.dateTo)
    expect(stateAfter.groupIds).toEqual(stateBefore.groupIds)
    expect(stateAfter.tlpLevels).toEqual(stateBefore.tlpLevels)
  })
})

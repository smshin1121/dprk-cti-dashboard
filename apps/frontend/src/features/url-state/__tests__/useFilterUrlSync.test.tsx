import { render, act } from '@testing-library/react'
import type { ReactNode } from 'react'
import {
  BrowserRouter,
  Routes,
  Route,
  useNavigate,
} from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useDashboardViewStore } from '../../../stores/dashboardView'
import { useFilterStore } from '../../../stores/filters'
import { useFilterUrlSync } from '../useFilterUrlSync'

function Probe(): null {
  useFilterUrlSync()
  return null
}

function NavButton({ to }: { to: string }): JSX.Element {
  const navigate = useNavigate()
  return (
    <button data-testid={`nav-${to}`} onClick={() => navigate(to)}>
      nav
    </button>
  )
}

function mountAt(path: string, children: ReactNode = <Probe />) {
  window.history.replaceState(null, '', path)
  return render(
    <BrowserRouter>
      <Routes>
        <Route path="*" element={<>{children}<NavButton to="/dashboard" /><NavButton to="/reports" /></>} />
      </Routes>
    </BrowserRouter>,
  )
}

function resetAll(): void {
  useFilterStore.setState({
    dateFrom: null,
    dateTo: null,
    groupIds: [],
    tlpLevels: [],
  })
  useDashboardViewStore.setState({ view: null, tab: null })
  window.history.replaceState(null, '', '/')
}

beforeEach(() => {
  resetAll()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useFilterUrlSync — mount hydration', () => {
  it('hydrates the filter store from the initial URL', () => {
    mountAt('/reports?date_from=2026-01-01&date_to=2026-04-18&group_id=3&group_id=1')
    const state = useFilterStore.getState()
    expect(state.dateFrom).toBe('2026-01-01')
    expect(state.dateTo).toBe('2026-04-18')
    // Canonicalized at decode — ascending.
    expect(state.groupIds).toEqual([1, 3])
  })

  it('does NOT hydrate tlpLevels from URL (plan D4 lock)', () => {
    useFilterStore.setState({ tlpLevels: ['AMBER'] })
    mountAt('/reports?date_from=2026-01-01&tlp=WHITE')
    // TLP is UI-only. URL must not clobber existing UI selection
    // even if a stray `tlp=` param is present.
    expect(useFilterStore.getState().tlpLevels).toEqual(['AMBER'])
  })

  it('hydrates view/tab ONLY on /dashboard route', () => {
    mountAt('/dashboard?view=attack&tab=overview')
    expect(useDashboardViewStore.getState().view).toBe('attack')
    expect(useDashboardViewStore.getState().tab).toBe('overview')
  })

  it('does NOT hydrate view/tab on non-dashboard routes', () => {
    mountAt('/reports?view=attack&tab=overview')
    expect(useDashboardViewStore.getState().view).toBeNull()
    expect(useDashboardViewStore.getState().tab).toBeNull()
  })
})

describe('useFilterUrlSync — emit to URL', () => {
  it('writes filter store changes to the URL via replaceState', () => {
    mountAt('/reports')
    const spy = vi.spyOn(window.history, 'replaceState')

    act(() => {
      useFilterStore.setState({
        dateFrom: '2026-02-01',
        dateTo: '2026-03-31',
        groupIds: [2, 5],
      })
    })

    expect(spy).toHaveBeenCalled()
    expect(window.location.search).toContain('date_from=2026-02-01')
    expect(window.location.search).toContain('date_to=2026-03-31')
    expect(window.location.search).toMatch(/group_id=2(&group_id=5)/)
  })

  it('canonicalizes equivalent groupIds sets to the same URL', () => {
    mountAt('/reports')

    act(() => {
      useFilterStore.setState({ groupIds: [3, 1] })
    })
    const firstSearch = window.location.search

    act(() => {
      useFilterStore.setState({ groupIds: [1, 3] })
    })
    const secondSearch = window.location.search

    expect(firstSearch).toBe(secondSearch)
    expect(firstSearch).toBe('?group_id=1&group_id=3')
  })

  // Plan D4 lock — TLP toggle must NEVER touch the URL. Three guards
  // already protect this at the type/encode/decode layers; this test
  // pins the runtime behaviour of the hook itself.
  it('TLP toggle does NOT touch the URL at all', () => {
    mountAt('/reports?date_from=2026-01-01')
    const spy = vi.spyOn(window.history, 'replaceState')

    act(() => {
      useFilterStore.getState().toggleTlpLevel('AMBER')
    })
    act(() => {
      useFilterStore.getState().toggleTlpLevel('WHITE')
    })

    // Neither toggle triggered a URL write.
    expect(spy).not.toHaveBeenCalled()
    expect(window.location.search).toBe('?date_from=2026-01-01')
  })

  it('no-op when encoded state already matches current URL', () => {
    mountAt('/reports?date_from=2026-01-01&group_id=1&group_id=3')
    const spy = vi.spyOn(window.history, 'replaceState')

    act(() => {
      // Trigger a "set same values" transition — canonical shape
      // matches URL, hook must not write.
      useFilterStore.setState({
        dateFrom: '2026-01-01',
        dateTo: null,
        groupIds: [1, 3],
      })
    })

    expect(spy).not.toHaveBeenCalled()
  })

  it('view/tab DO NOT reach the URL on non-dashboard routes', () => {
    mountAt('/reports')

    act(() => {
      useDashboardViewStore.setState({ view: 'attack', tab: 'overview' })
    })

    expect(window.location.search).not.toContain('view=')
    expect(window.location.search).not.toContain('tab=')
  })

  it('view/tab DO reach the URL on /dashboard route', () => {
    mountAt('/dashboard')

    act(() => {
      useDashboardViewStore.setState({ view: 'attack', tab: 'overview' })
    })

    expect(window.location.search).toContain('view=attack')
    expect(window.location.search).toContain('tab=overview')
  })
})

describe('useFilterUrlSync — popstate rehydration', () => {
  it('re-hydrates store when the URL changes via back/forward', () => {
    mountAt('/reports?date_from=2026-01-01')
    expect(useFilterStore.getState().dateFrom).toBe('2026-01-01')

    // Simulate a browser back: replace URL, dispatch popstate.
    act(() => {
      window.history.replaceState(
        null,
        '',
        '/reports?date_from=2025-12-01&group_id=7',
      )
      window.dispatchEvent(new PopStateEvent('popstate'))
    })

    expect(useFilterStore.getState().dateFrom).toBe('2025-12-01')
    expect(useFilterStore.getState().groupIds).toEqual([7])
  })
})

describe('useFilterUrlSync — loop guard', () => {
  it('does not ping-pong replaceState on a single filter change', () => {
    mountAt('/reports')
    const spy = vi.spyOn(window.history, 'replaceState')

    act(() => {
      useFilterStore.setState({ dateFrom: '2026-02-01' })
    })

    // Exactly one write for one user change. More than one would
    // mean the emit effect re-fired due to a URL change it caused
    // itself (classic hydrate-emit ping-pong).
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('mount hydration + emit does not loop when URL was non-canonical', () => {
    // Non-canonical incoming URL: group_id=3,1 canonicalizes to [1,3]
    // → emit writes group_id=1,3 once (canonicalization write). After
    // that, store and URL agree; no further writes.
    //
    // Prime the URL BEFORE the spy so `mountAt`'s own setup call is
    // not counted. The spy then captures exactly the writes the hook
    // triggers.
    window.history.replaceState(null, '', '/reports?group_id=3&group_id=1')
    const spy = vi.spyOn(window.history, 'replaceState')

    render(
      <BrowserRouter>
        <Routes>
          <Route path="*" element={<Probe />} />
        </Routes>
      </BrowserRouter>,
    )

    // Filter for writes made by this hook (react-router's
    // BrowserRouter also calls replaceState once on mount with
    // url=undefined to inject its own state key — not our concern).
    const hookWrites = spy.mock.calls.filter(
      ([, , url]) => typeof url === 'string' && url.includes('/reports'),
    )
    // Exactly one canonicalization write. More than 1 = the emit
    // effect is firing repeatedly because the URL write it caused
    // is being picked up as "URL changed externally" and re-
    // hydrating into the store.
    expect(hookWrites).toHaveLength(1)
    expect(hookWrites[0][2]).toBe('/reports?group_id=1&group_id=3')
    expect(window.location.search).toBe('?group_id=1&group_id=3')
  })
})

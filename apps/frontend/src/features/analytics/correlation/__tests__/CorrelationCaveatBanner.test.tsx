/**
 * Plan §B8 (d) — caveat banner dismiss-once-per-session.
 *
 * RED state at T7. T9 implements the component (sticky banner with
 * dismiss button + sessionStorage-backed dismissed flag via
 * `useSyncExternalStore` over a tiny zustand slice). Until then
 * every test below fails at runtime with the stub's
 * `NotImplementedError` message — clean, traceable RED signal per
 * `pattern_tdd_stub_for_red_collection`.
 *
 * Q3 default — `sessionStorage` (per-tab), NOT `localStorage`. The
 * §0.1 amendment 2026-05-08 (T7 dispatch) aligns plan §5 risk row
 * (which had said "localStorage persistence keyed by
 * <session_uuid>") with §8 Q3 (which is the user-decision lock).
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { CorrelationCaveatBanner } from '../CorrelationCaveatBanner'

const STORAGE_KEY = 'correlation.banner.dismissed'

beforeEach(() => {
  window.sessionStorage.clear()
})

afterEach(() => {
  window.sessionStorage.clear()
})

describe('CorrelationCaveatBanner — dismiss-once-per-tab (Q3 default)', () => {
  it('renders the caveat copy on first mount when nothing is stored', () => {
    render(<CorrelationCaveatBanner />)
    // The banner ships with copy describing "correlation ≠ causation"
    // (umbrella §6.3). T9 wires in the i18n key
    // `correlation.caveat.title`. Test asserts visibility, not exact
    // string, so an i18n re-key doesn't ripple.
    expect(screen.getByTestId('correlation-caveat-banner')).toBeVisible()
  })

  it('hides after the dismiss button is clicked', async () => {
    const user = userEvent.setup()
    render(<CorrelationCaveatBanner />)
    expect(screen.getByTestId('correlation-caveat-banner')).toBeVisible()

    await user.click(screen.getByTestId('correlation-caveat-dismiss'))

    expect(screen.queryByTestId('correlation-caveat-banner')).toBeNull()
  })

  it('writes the dismissed flag to sessionStorage on dismiss (Q3 — NOT localStorage)', async () => {
    const user = userEvent.setup()
    render(<CorrelationCaveatBanner />)
    await user.click(screen.getByTestId('correlation-caveat-dismiss'))

    // sessionStorage records the per-tab decision.
    expect(window.sessionStorage.getItem(STORAGE_KEY)).not.toBeNull()
    // localStorage stays untouched — Q3 explicitly chose per-tab scope.
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('stays hidden across remounts within the same tab/session', () => {
    // Simulate a prior dismissal in this session/tab.
    window.sessionStorage.setItem(STORAGE_KEY, '1')

    render(<CorrelationCaveatBanner />)
    expect(screen.queryByTestId('correlation-caveat-banner')).toBeNull()
  })

  it('reappears in a "new tab" (sessionStorage cleared)', () => {
    // Same tab — dismissed.
    window.sessionStorage.setItem(STORAGE_KEY, '1')
    const { unmount } = render(<CorrelationCaveatBanner />)
    expect(screen.queryByTestId('correlation-caveat-banner')).toBeNull()
    unmount()

    // "New tab" — sessionStorage starts empty.
    window.sessionStorage.clear()
    render(<CorrelationCaveatBanner />)
    expect(screen.getByTestId('correlation-caveat-banner')).toBeVisible()
  })
})

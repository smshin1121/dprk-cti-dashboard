import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LocaleToggle } from '../LocaleToggle'
import { i18n } from '../../i18n'

beforeEach(async () => {
  // Reset to known language so test order doesn't skew assertions.
  await i18n.changeLanguage('ko')
  // Clear the detector's localStorage cache so each test starts
  // with a deterministic signal.
  window.localStorage.removeItem('i18nextLng')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('LocaleToggle', () => {
  it('renders current locale code in the button', () => {
    render(<LocaleToggle />)
    const btn = screen.getByTestId('locale-toggle')
    expect(btn).toHaveAttribute('data-locale', 'ko')
    expect(btn).toHaveTextContent('ko')
  })

  it('cycles ko → en on click and persists via localStorage', async () => {
    const user = userEvent.setup()
    render(<LocaleToggle />)
    await user.click(screen.getByTestId('locale-toggle'))
    expect(i18n.resolvedLanguage).toBe('en')
    expect(window.localStorage.getItem('i18nextLng')).toBe('en')
  })

  it('cycles en → ko on second click', async () => {
    const user = userEvent.setup()
    await i18n.changeLanguage('en')
    render(<LocaleToggle />)
    await user.click(screen.getByTestId('locale-toggle'))
    expect(i18n.resolvedLanguage).toBe('ko')
  })

  it('triggers no replaceState / URL change on locale switch', async () => {
    // Plan D4 + D5 isolation: URL state must not include locale.
    // Beyond the static whitelist check in urlState.test.ts, pin
    // the RUNTIME behaviour here: clicking the toggle does NOT
    // invoke history.replaceState.
    const spy = vi.spyOn(window.history, 'replaceState')
    const user = userEvent.setup()
    render(<LocaleToggle />)
    await user.click(screen.getByTestId('locale-toggle'))
    expect(spy).not.toHaveBeenCalled()
  })
})

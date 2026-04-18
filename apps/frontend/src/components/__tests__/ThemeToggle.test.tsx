import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import { useThemeStore } from '../../stores/theme'
import { ThemeToggle } from '../ThemeToggle'

function resetTheme(): void {
  document.documentElement.removeAttribute('data-theme')
  window.localStorage.clear()
  useThemeStore.setState({ mode: 'system' })
}

describe('ThemeToggle', () => {
  beforeEach(resetTheme)

  it.each(['light', 'dark', 'system'] as const)(
    'exposes the current mode via data attribute + aria-label when set to %s',
    (mode) => {
      useThemeStore.getState().setMode(mode)
      render(<ThemeToggle />)
      const btn = screen.getByTestId('theme-toggle')
      expect(btn.getAttribute('data-theme-mode')).toBe(mode)
      // aria-label carries both current mode and next action, so
      // screen readers get the full context without trial-clicking.
      expect(btn.getAttribute('aria-label')).toContain(`Theme: ${mode}`)
    },
  )

  it('clicking cycles light → dark → system → light', async () => {
    const user = userEvent.setup()
    useThemeStore.getState().setMode('light')
    render(<ThemeToggle />)
    const btn = screen.getByTestId('theme-toggle')

    await user.click(btn)
    expect(useThemeStore.getState().mode).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')

    await user.click(btn)
    expect(useThemeStore.getState().mode).toBe('system')
    expect(document.documentElement.getAttribute('data-theme')).toBe('system')

    await user.click(btn)
    expect(useThemeStore.getState().mode).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })

  it('aria-label describes the next action so screen-reader users can predict the click outcome', () => {
    useThemeStore.getState().setMode('light')
    render(<ThemeToggle />)
    expect(
      screen.getByTestId('theme-toggle').getAttribute('aria-label'),
    ).toMatch(/switch to dark/i)
  })
})

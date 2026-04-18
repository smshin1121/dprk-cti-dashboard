import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  CYCLE_ORDER,
  THEME_MODES,
  THEME_STORAGE_KEY,
  isValidThemeMode,
  useThemeStore,
} from '../theme'

function resetDom(): void {
  document.documentElement.removeAttribute('data-theme')
  window.localStorage.clear()
}

describe('isValidThemeMode', () => {
  it('accepts the three valid modes', () => {
    expect(isValidThemeMode('light')).toBe(true)
    expect(isValidThemeMode('dark')).toBe(true)
    expect(isValidThemeMode('system')).toBe(true)
  })

  it('rejects invalid + legacy values', () => {
    expect(isValidThemeMode('auto')).toBe(false)
    expect(isValidThemeMode('')).toBe(false)
    expect(isValidThemeMode(null)).toBe(false)
    expect(isValidThemeMode(undefined)).toBe(false)
    expect(isValidThemeMode(123)).toBe(false)
  })
})

describe('useThemeStore.setMode', () => {
  beforeEach(() => {
    resetDom()
    useThemeStore.setState({ mode: 'system' })
  })

  afterEach(() => {
    resetDom()
  })

  it.each(THEME_MODES)('writes %s to data-theme and localStorage', (mode) => {
    useThemeStore.getState().setMode(mode)
    expect(document.documentElement.getAttribute('data-theme')).toBe(mode)
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe(mode)
    expect(useThemeStore.getState().mode).toBe(mode)
  })

  it('ignores invalid mode input (defense against bad callers)', () => {
    useThemeStore.getState().setMode('light')
    useThemeStore.getState().setMode('not-a-mode' as never)
    expect(useThemeStore.getState().mode).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })
})

describe('useThemeStore.cycleMode', () => {
  beforeEach(() => {
    resetDom()
  })

  it('follows the documented CYCLE_ORDER: light → dark → system → light', () => {
    expect(CYCLE_ORDER).toEqual(['light', 'dark', 'system'])
    useThemeStore.setState({ mode: 'light' })
    useThemeStore.getState().cycleMode()
    expect(useThemeStore.getState().mode).toBe('dark')
    useThemeStore.getState().cycleMode()
    expect(useThemeStore.getState().mode).toBe('system')
    useThemeStore.getState().cycleMode()
    expect(useThemeStore.getState().mode).toBe('light')
  })

  it('writes each cycle step to both data-theme and localStorage', () => {
    useThemeStore.setState({ mode: 'light' })
    useThemeStore.getState().cycleMode()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })
})

describe('FOUC-script ↔ store storage-key contract', () => {
  // Regression guard: the inline FOUC script in index.html hard-codes
  // the storage key and the valid-mode check. If the store's
  // THEME_STORAGE_KEY or accepted values drift, the FOUC script
  // silently falls back to 'system' on every page load — the user's
  // preference would appear to "reset" on each refresh. This test
  // reads both files and asserts the contract is in sync.

  it('index.html inline script uses the same storage key the store writes', () => {
    const indexHtml = readFileSync(
      resolve(__dirname, '..', '..', '..', 'index.html'),
      'utf-8',
    )
    expect(indexHtml).toContain(`'${THEME_STORAGE_KEY}'`)
  })

  it('index.html inline script validates all THEME_MODES the store accepts', () => {
    const indexHtml = readFileSync(
      resolve(__dirname, '..', '..', '..', 'index.html'),
      'utf-8',
    )
    // The script should accept every mode the store accepts. A mode
    // the store writes but the script rejects would reset the
    // preference on reload.
    for (const mode of THEME_MODES) {
      expect(indexHtml).toContain(`'${mode}'`)
    }
  })
})

import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  DESIGN_PRESETS,
  PRESET_STORAGE_KEY,
  isValidPreset,
  usePresetStore,
} from '../preset'

function resetPreset(): void {
  document.documentElement.removeAttribute('data-preset')
  window.localStorage.clear()
  usePresetStore.setState({ preset: 'default' })
}

describe('isValidPreset', () => {
  it('accepts the design comparison presets', () => {
    for (const preset of DESIGN_PRESETS) {
      expect(isValidPreset(preset)).toBe(true)
    }
  })

  it('rejects invalid + stale values', () => {
    expect(isValidPreset('purple')).toBe(false)
    expect(isValidPreset('')).toBe(false)
    expect(isValidPreset(null)).toBe(false)
    expect(isValidPreset(undefined)).toBe(false)
  })
})

describe('usePresetStore.setPreset', () => {
  beforeEach(resetPreset)
  afterEach(resetPreset)

  it.each(['sentry', 'wired', 'linear'] as const)(
    'writes %s to data-preset and localStorage',
    (preset) => {
      usePresetStore.getState().setPreset(preset)
      expect(document.documentElement.getAttribute('data-preset')).toBe(preset)
      expect(window.localStorage.getItem(PRESET_STORAGE_KEY)).toBe(preset)
      expect(usePresetStore.getState().preset).toBe(preset)
    },
  )

  it('removes data-preset when reset to default', () => {
    usePresetStore.getState().setPreset('sentry')
    usePresetStore.getState().setPreset('default')

    expect(document.documentElement.hasAttribute('data-preset')).toBe(false)
    expect(window.localStorage.getItem(PRESET_STORAGE_KEY)).toBe('default')
    expect(usePresetStore.getState().preset).toBe('default')
  })

  it('ignores invalid preset input', () => {
    usePresetStore.getState().setPreset('wired')
    usePresetStore.getState().setPreset('not-a-preset' as never)

    expect(usePresetStore.getState().preset).toBe('wired')
    expect(document.documentElement.getAttribute('data-preset')).toBe('wired')
  })
})

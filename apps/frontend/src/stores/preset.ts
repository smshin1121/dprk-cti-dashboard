/**
 * Design-preset picker: zustand + localStorage + DOM side-effect.
 *
 * Dev-only state for PR #25 Step 1 (3-way token comparison). Mirrors
 * the useThemeStore pattern: one field, localStorage persistence,
 * html[data-preset] attribute write on every change. The preset CSS
 * files (`styles/presets/*.css`) scope their overrides to
 * `:root[data-preset="{name}"]` so an absent or "default" value keeps
 * the current tokens.css scaffold active.
 *
 * Prod behavior: the Shell mounts the picker only behind
 * `import.meta.env.DEV`, so prod builds never read this store's
 * selectors. Shell loads the overlay through a dev-only dynamic
 * import so this store and its DOM side effect stay out of prod.
 *
 * When Step 1 picks a winner, this store + CSS preset files are
 * deleted and the winning palette moves into the committed
 * `tokens.css` (PR #25 Group A). The chore/cleanup is tracked in
 * the PR #25 plan Group A description.
 */

import { create } from 'zustand'

export const PRESET_STORAGE_KEY = 'dprk-cti.design-preset'

export const DESIGN_PRESETS = ['default', 'sentry', 'wired', 'linear'] as const
export type DesignPreset = (typeof DESIGN_PRESETS)[number]

export function isValidPreset(value: unknown): value is DesignPreset {
  return (
    value === 'default' ||
    value === 'sentry' ||
    value === 'wired' ||
    value === 'linear'
  )
}

export interface PresetState {
  preset: DesignPreset
  setPreset: (preset: DesignPreset) => void
}

function readStoredPreset(): DesignPreset {
  if (typeof window === 'undefined') return 'default'
  try {
    const raw = window.localStorage.getItem(PRESET_STORAGE_KEY)
    return isValidPreset(raw) ? raw : 'default'
  } catch {
    return 'default'
  }
}

function writeStoredPreset(preset: DesignPreset): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(PRESET_STORAGE_KEY, preset)
  } catch {
    /* private mode / quota: DOM attribute still reflects intent */
  }
}

function applyPresetToDocument(preset: DesignPreset): void {
  if (typeof document === 'undefined') return
  if (preset === 'default') {
    document.documentElement.removeAttribute('data-preset')
  } else {
    document.documentElement.setAttribute('data-preset', preset)
  }
}

export const usePresetStore = create<PresetState>((set) => {
  const initial = readStoredPreset()
  applyPresetToDocument(initial)

  return {
    preset: initial,
    setPreset: (preset) => {
      if (!isValidPreset(preset)) return
      writeStoredPreset(preset)
      applyPresetToDocument(preset)
      set({ preset })
    },
  }
})

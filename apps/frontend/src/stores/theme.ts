/**
 * Theme preference — zustand + localStorage + DOM side-effect.
 *
 * State shape (plan D4 lock): one field — `mode: 'light' | 'dark' |
 * 'system'`. Default 'system' respects the OS preference via the
 * CSS media query in tokens.css; no JS subscription to
 * matchMedia is needed because CSS handles the runtime change
 * while the mode is 'system'.
 *
 * Side effects
 * ------------
 * - Writes `html[data-theme]` synchronously on every mode change
 *   so Tailwind's `dark:` variant + CSS var cascade update in the
 *   same paint frame.
 * - Persists to localStorage under `THEME_STORAGE_KEY`. The FOUC
 *   script in `index.html` reads this same key before React
 *   hydrates — changing the key here without updating index.html
 *   (or vice versa) breaks the first-paint contract. A
 *   tests/theme-storage-contract.test pins both.
 *
 * D10 compliance
 * --------------
 * Theme is UI state, not server state — zustand is the right home.
 * No server endpoint knows or cares about the user's theme choice.
 */

import { create } from 'zustand'

export const THEME_STORAGE_KEY = 'dprk-cti.theme'

export const THEME_MODES = ['light', 'dark', 'system'] as const
export type ThemeMode = (typeof THEME_MODES)[number]

export function isValidThemeMode(value: unknown): value is ThemeMode {
  return (
    value === 'light' || value === 'dark' || value === 'system'
  )
}

export interface ThemeState {
  mode: ThemeMode
  setMode: (mode: ThemeMode) => void
  /** Cycle light → dark → system → light. Useful for a single-
   * button toggle affordance in the topbar. */
  cycleMode: () => void
}

function readStoredMode(): ThemeMode {
  if (typeof window === 'undefined') return 'system'
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isValidThemeMode(raw) ? raw : 'system'
  } catch {
    return 'system'
  }
}

function writeStoredMode(mode: ThemeMode): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, mode)
  } catch {
    // Storage can fail (Safari private mode quota, disabled
    // storage). Silently drop — the DOM attribute still reflects
    // the intent for this session.
  }
}

function applyModeToDocument(mode: ThemeMode): void {
  if (typeof document === 'undefined') return
  document.documentElement.setAttribute('data-theme', mode)
}

/** Order used by `cycleMode`. Kept exported so tests can pin the
 *  intended sequence without depending on the implementation. */
export const CYCLE_ORDER: readonly ThemeMode[] = ['light', 'dark', 'system']

function nextInCycle(current: ThemeMode): ThemeMode {
  const i = CYCLE_ORDER.indexOf(current)
  return CYCLE_ORDER[(i + 1) % CYCLE_ORDER.length]
}

export const useThemeStore = create<ThemeState>((set, get) => {
  // Seed from localStorage on store creation so the in-memory
  // state matches what the FOUC script already wrote to the DOM.
  // Mismatches here would cause a one-frame flash to the default
  // when React hydrates.
  const initial = readStoredMode()
  applyModeToDocument(initial)

  return {
    mode: initial,
    setMode: (mode) => {
      if (!isValidThemeMode(mode)) return
      writeStoredMode(mode)
      applyModeToDocument(mode)
      set({ mode })
    },
    cycleMode: () => {
      const next = nextInCycle(get().mode)
      writeStoredMode(next)
      applyModeToDocument(next)
      set({ mode: next })
    },
  }
})

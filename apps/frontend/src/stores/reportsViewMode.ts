/**
 * Reports view-mode preference — zustand + localStorage.
 *
 * State shape: one field — `mode: 'list' | 'timeline'`. Default
 * `'list'` preserves the current ListTable behavior so existing
 * users see no change until they pick the toggle.
 *
 * Mirrors the `useThemeStore` pattern (zustand + localStorage),
 * minus the DOM side-effect — view mode is purely in-app state, no
 * CSS variable cascade needed.
 *
 * D10 compliance: view mode is UI state, not server state — zustand
 * is the right home. No server endpoint knows the user's view
 * choice and the same `useReportsList` query feeds both views.
 */

import { create } from 'zustand'

export const REPORTS_VIEW_MODE_STORAGE_KEY = 'dprk-cti.reports-view-mode'

export const REPORTS_VIEW_MODES = ['list', 'timeline'] as const
export type ReportsViewMode = (typeof REPORTS_VIEW_MODES)[number]

export function isValidReportsViewMode(
  value: unknown,
): value is ReportsViewMode {
  return value === 'list' || value === 'timeline'
}

export interface ReportsViewModeState {
  mode: ReportsViewMode
  setMode: (mode: ReportsViewMode) => void
  /** Flip list ↔ timeline. Two-state cycle, no third value. */
  toggleMode: () => void
}

function readStoredMode(): ReportsViewMode {
  if (typeof window === 'undefined') return 'list'
  try {
    const raw = window.localStorage.getItem(REPORTS_VIEW_MODE_STORAGE_KEY)
    return isValidReportsViewMode(raw) ? raw : 'list'
  } catch {
    return 'list'
  }
}

function writeStoredMode(mode: ReportsViewMode): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(REPORTS_VIEW_MODE_STORAGE_KEY, mode)
  } catch {
    // Storage can fail (private mode quota). Silently drop — the
    // in-memory state still reflects the intent for this session.
  }
}

export const useReportsViewModeStore = create<ReportsViewModeState>(
  (set, get) => {
    const initial = readStoredMode()
    return {
      mode: initial,
      setMode: (mode) => {
        if (!isValidReportsViewMode(mode)) return
        writeStoredMode(mode)
        set({ mode })
      },
      toggleMode: () => {
        const next: ReportsViewMode = get().mode === 'list' ? 'timeline' : 'list'
        writeStoredMode(next)
        set({ mode: next })
      },
    }
  },
)

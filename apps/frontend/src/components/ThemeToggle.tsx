/**
 * Three-state theme toggle — light → dark → system → light.
 *
 * Plan D4 ships this as a standalone topbar affordance for PR #12.
 * Plan D5 / Group G will move this component into the user menu 👤
 * dropdown and expose the same action inside Command Palette. Both
 * consumers read from `useThemeStore.cycleMode` — the click handler
 * surface is identical.
 *
 * Accessibility
 * -------------
 * - `aria-label` announces both the CURRENT mode and the next
 *   action ("Theme: dark; switch to system"). Screen readers give
 *   the user both pieces without requiring them to guess what
 *   clicking will do.
 * - Visible icon matches the current mode so sighted users don't
 *   have to click to discover state.
 * - `title` matches `aria-label` for hover hint.
 *
 * No Radix dialog / menu — the three-state cycle is one button and
 * doesn't need a surface. When Group G lands the user menu, this
 * component stays a button; only its parent moves.
 */

import { Monitor, Moon, Sun } from 'lucide-react'

import { useThemeStore, type ThemeMode } from '../stores/theme'

const ICONS: Record<ThemeMode, typeof Sun> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
}

const LABELS: Record<ThemeMode, string> = {
  light: 'light',
  dark: 'dark',
  system: 'system',
}

function nextLabel(current: ThemeMode): string {
  switch (current) {
    case 'light':
      return 'dark'
    case 'dark':
      return 'system'
    case 'system':
      return 'light'
  }
}

export function ThemeToggle(): JSX.Element {
  const mode = useThemeStore((s) => s.mode)
  const cycleMode = useThemeStore((s) => s.cycleMode)
  const Icon = ICONS[mode]
  const description = `Theme: ${LABELS[mode]}; switch to ${nextLabel(mode)}`

  return (
    <button
      type="button"
      onClick={cycleMode}
      aria-label={description}
      title={description}
      data-testid="theme-toggle"
      data-theme-mode={mode}
      className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border-card bg-surface text-ink-muted transition-colors hover:border-border-strong hover:text-ink"
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
    </button>
  )
}

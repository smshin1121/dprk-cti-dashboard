/**
 * Two-state toggle: list ↔ timeline view for the /reports page.
 *
 * Mirrors the ThemeToggle / LocaleToggle visual posture (single
 * icon button in a square frame). Click flips the mode.
 *
 * Accessibility: aria-label and title both announce the NEXT
 * action — "Switch to timeline view" when in list mode and
 * vice versa — so the click outcome is unambiguous before
 * activation. The visible icon shows the OTHER mode (the one a
 * click would switch TO), matching the aria-label.
 */

import { History, List } from 'lucide-react'

import {
  type ReportsViewMode,
  useReportsViewModeStore,
} from '../stores/reportsViewMode'

const NEXT_LABEL: Record<ReportsViewMode, string> = {
  list: 'Switch to timeline view',
  timeline: 'Switch to list view',
}

export function ReportsViewModeToggle(): JSX.Element {
  const mode = useReportsViewModeStore((s) => s.mode)
  const toggle = useReportsViewModeStore((s) => s.toggleMode)
  const Icon = mode === 'list' ? History : List
  const description = NEXT_LABEL[mode]

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={description}
      title={description}
      data-testid="reports-view-mode-toggle"
      data-view-mode={mode}
      className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border-card bg-surface text-ink-muted transition-colors hover:border-border-strong hover:text-ink"
    >
      <Icon className="h-4 w-4" aria-hidden="true" />
    </button>
  )
}

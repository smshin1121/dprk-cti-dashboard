/**
 * Alerts drawer — design doc §4.2 area [F].
 *
 * **Scope: STATIC SHELL.** Plan §1 explicit non-goal: real-time
 * alerts (WebSocket / SSE / polling) ship in Phase 4. Plan §4 Group I
 * deliverable is the shell + empty state ONLY.
 *
 * What the shell IS:
 *   - A topbar-adjacent trigger button + a slide-in drawer panel.
 *   - Local React state (`useState<boolean>`) for open/closed —
 *     this deliberately does NOT live in zustand because:
 *       1) the drawer's open-state is strictly ephemeral UI
 *          (plan D4: ephemeral UI state does NOT enter URL-state),
 *       2) nothing else in the app needs to read or write it, and
 *       3) keeping it local makes the invariant "no global state
 *          touched by the shell" trivially verifiable.
 *   - Escape-to-close + click-outside-to-close + a Close button
 *     for keyboard / mouse / screen-reader parity.
 *   - A static empty state + phase-4 note so analysts understand
 *     why the drawer is inert before Phase 4 lands.
 *
 * What the shell IS NOT:
 *   - Not a fetch — zero React Query hooks, zero network calls.
 *     The `noFetch` invariant test pins this with a spy.
 *   - Not a notification badge / unread-count — those imply data
 *     state, which is Phase 4.
 *   - Not a focus trap — a trap for a static empty surface is
 *     over-engineered; Escape + outside-click cover keyboard users.
 *
 * When Phase 4 real-time wiring lands:
 *   Swap the empty state for a hook-driven list; add a badge on
 *   the trigger; retain the drawer scaffold. `data-phase-status`
 *   flips from "static-shell" to "live".
 */

import { Bell } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { cn } from '../../lib/utils'

export function AlertsDrawer(): JSX.Element {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!open) return
    function onKeydown(event: KeyboardEvent): void {
      if (event.key === 'Escape') setOpen(false)
    }
    function onClickOutside(event: MouseEvent): void {
      const panel = panelRef.current
      const trigger = triggerRef.current
      const target = event.target
      if (!(target instanceof Node)) return
      if (panel && panel.contains(target)) return
      if (trigger && trigger.contains(target)) return
      setOpen(false)
    }
    window.addEventListener('keydown', onKeydown)
    window.addEventListener('mousedown', onClickOutside)
    return () => {
      window.removeEventListener('keydown', onKeydown)
      window.removeEventListener('mousedown', onClickOutside)
    }
  }, [open])

  return (
    <div data-testid="alerts-drawer-root" data-phase-status="static-shell" data-phase="phase-4">
      <button
        type="button"
        ref={triggerRef}
        data-testid="alerts-drawer-trigger"
        aria-label={t('dashboard.alerts.trigger')}
        aria-expanded={open}
        aria-controls="alerts-drawer-panel"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'inline-flex items-center gap-2 rounded-none border border-border-card bg-surface px-3 py-1.5 text-xs font-cta uppercase tracking-cta text-ink',
          'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
        )}
      >
        <Bell aria-hidden className="h-4 w-4" />
        {t('dashboard.alerts.trigger')}
      </button>

      {open ? (
        <div
          id="alerts-drawer-panel"
          ref={panelRef}
          data-testid="alerts-drawer-panel"
          role="dialog"
          aria-modal="false"
          aria-labelledby="alerts-drawer-heading"
          className={cn(
            'fixed right-4 top-20 z-40 flex w-80 max-w-[90vw] flex-col gap-3 rounded-none border border-border-card bg-surface p-4 shadow-lg',
          )}
        >
          <header className="flex items-center justify-between">
            <h3
              id="alerts-drawer-heading"
              className="text-sm font-semibold text-ink"
            >
              {t('dashboard.alerts.title')}
            </h3>
            <button
              type="button"
              data-testid="alerts-drawer-close"
              onClick={() => setOpen(false)}
              className={cn(
                'rounded-none border border-border-card bg-app px-2 py-1 text-[10px] font-cta uppercase tracking-cta text-ink-muted',
                'hover:border-border-strong hover:text-ink focus:outline-none focus:ring-2 focus:ring-ring',
              )}
            >
              {t('dashboard.alerts.close')}
            </button>
          </header>
          <div
            data-testid="alerts-drawer-empty"
            className="flex flex-1 flex-col gap-3 rounded-none border border-dashed border-border-card bg-app p-4"
          >
            <p className="text-sm text-ink-muted">
              {t('dashboard.alerts.empty')}
            </p>
            <p
              data-testid="alerts-drawer-phase-note"
              className="text-[11px] font-cta uppercase tracking-caption text-ink-subtle"
            >
              {t('dashboard.alerts.phaseNote')}
            </p>
          </div>
        </div>
      ) : null}
    </div>
  )
}

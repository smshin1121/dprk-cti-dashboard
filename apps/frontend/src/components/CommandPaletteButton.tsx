/**
 * Command palette — trigger button + ⌘K dialog with navigation
 * commands. Plan D3 lock (PR #13 Group D).
 *
 * PR #12 Group G shipped the shell: trigger button, mod+k shortcut,
 * editable-target guard, empty placeholder dialog. PR #13 Group D
 * swaps the placeholder for the real command list while preserving
 * every contract that shell covered.
 *
 * Command set (plan D3 — deliberately narrow):
 *   - Navigate: /dashboard, /reports, /incidents, /actors
 *   - View:     theme cycle, clear filters
 *   - Session:  sign out
 *
 * Deliberately OUT of scope (plan D3 + §1 non-goals):
 *   - Full-text / server-backed search
 *   - Any mutation / bulk action
 *   - Expanded action taxonomy (attach, export, etc.)
 *
 * Ownership boundaries:
 *   - Navigation → react-router `useNavigate()` (no hook indirection).
 *   - Theme cycle → `useThemeStore().cycleMode()` — DOM side-effect
 *     handled inside the store per its existing contract.
 *   - Clear filters → `useFilterStore().clear()` — resets date range,
 *     group selection, AND tlp levels (plan D4 lock: user choice
 *     reset regardless of whether tlp crosses the wire).
 *   - Sign out → same pattern as `UserMenu`: mutate, navigate on
 *     success. `useLogout` explicitly does not know about the router
 *     so the navigate stays here.
 *
 * Shortcut discipline (carried from PR #12):
 *   - mod+k toggles the dialog globally.
 *   - Early-exits when focus is inside input / textarea /
 *     contenteditable / select so date inputs don't get hijacked.
 *
 * i18n preparation:
 *   Labels come from `lib/commands.ts::getCommandLabel`. No display
 *   strings hardcoded inline; Group F routes the getter through
 *   `react-i18next.t(...)` in one edit.
 */

import { Command } from 'cmdk'
import { Command as CommandIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useLogout } from '../features/auth/useLogout'
import {
  COMMAND_DEFINITIONS,
  getCommandLabel,
  type CommandId,
} from '../lib/commands'
import { cn } from '../lib/utils'
import { useFilterStore } from '../stores/filters'
import { useThemeStore } from '../stores/theme'

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

/** Map a command id to the route path it navigates to. Keeping this
 *  next to `NAV_COMMAND_IDS` instead of in `commands.ts` because
 *  paths are router-specific and leak react-router knowledge; the
 *  registry stays pure. */
const NAV_PATHS: Record<
  Extract<CommandId, `nav.${string}`>,
  string
> = {
  'nav.dashboard': '/dashboard',
  'nav.reports': '/reports',
  'nav.incidents': '/incidents',
  'nav.actors': '/actors',
}

export function CommandPaletteButton(): JSX.Element {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const cycleTheme = useThemeStore((s) => s.cycleMode)
  const clearFilters = useFilterStore((s) => s.clear)
  const logoutMutation = useLogout()

  useEffect(() => {
    function handler(event: KeyboardEvent): void {
      if (event.key !== 'k' && event.key !== 'K') return
      if (!(event.metaKey || event.ctrlKey)) return
      if (isEditableTarget(event.target)) return
      event.preventDefault()
      setOpen((prev) => !prev)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  function runCommand(id: CommandId): void {
    // Close first so the dialog's exit transition starts before the
    // action potentially unmounts / re-renders this component (e.g.
    // logout wiping the query cache).
    setOpen(false)

    switch (id) {
      case 'nav.dashboard':
      case 'nav.reports':
      case 'nav.incidents':
      case 'nav.actors':
        navigate(NAV_PATHS[id])
        return
      case 'theme.cycle':
        cycleTheme()
        return
      case 'filters.clear':
        clearFilters()
        return
      case 'auth.logout':
        // Same pattern as UserMenu — the hook is router-unaware, the
        // caller owns the post-success navigation.
        logoutMutation.mutate(undefined, {
          onSuccess: () => navigate('/login'),
        })
        return
    }
  }

  return (
    <>
      <button
        type="button"
        data-testid="cmdk-trigger"
        onClick={() => setOpen(true)}
        aria-label="Open command palette"
        className={cn(
          'flex h-8 items-center gap-2 rounded border border-border-card bg-app px-3 text-xs text-ink-muted',
          'hover:border-signal hover:text-ink focus:outline-none focus:ring-2 focus:ring-signal',
        )}
      >
        <CommandIcon aria-hidden className="h-3 w-3" />
        <span>Search</span>
        <kbd
          className={cn(
            'ml-2 rounded border border-border-card bg-surface px-1 py-0.5 text-[10px] text-ink-subtle',
          )}
        >
          ⌘K
        </kbd>
      </button>

      <Command.Dialog
        open={open}
        onOpenChange={setOpen}
        label="Command palette"
        data-testid="cmdk-dialog"
        className={cn(
          'fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-20',
        )}
      >
        <div
          className={cn(
            'w-full max-w-lg overflow-hidden rounded-lg border border-border-card bg-surface text-ink shadow-xl',
          )}
        >
          <Command.Input
            data-testid="cmdk-input"
            placeholder="Type a command…"
            className={cn(
              'w-full border-b border-border-card bg-transparent px-4 py-3 text-sm outline-none placeholder:text-ink-subtle',
            )}
          />
          <Command.List
            data-testid="cmdk-list"
            className="max-h-[320px] overflow-auto py-1"
          >
            <Command.Empty
              data-testid="cmdk-empty"
              className="px-4 py-6 text-center text-sm text-ink-muted"
            >
              No matching command.
            </Command.Empty>

            {COMMAND_DEFINITIONS.map((def) => (
              <Command.Item
                key={def.id}
                value={[def.id, def.label, ...def.keywords].join(' ')}
                data-testid={`cmdk-item-${def.id}`}
                onSelect={() => runCommand(def.id)}
                className={cn(
                  'flex cursor-pointer items-center justify-between rounded px-4 py-2 text-sm',
                  'data-[selected=true]:bg-app',
                )}
              >
                <span>{getCommandLabel(def.id)}</span>
                <span className="text-[10px] uppercase tracking-wider text-ink-subtle">
                  {def.id}
                </span>
              </Command.Item>
            ))}
          </Command.List>
        </div>
      </Command.Dialog>
    </>
  )
}

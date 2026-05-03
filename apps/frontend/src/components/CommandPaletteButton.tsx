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
 *   - View:     clear filters
 *   - Session:  sign out
 *
 * Deliberately OUT of scope (plan D3 + §1 non-goals):
 *   - Full-text / server-backed search
 *   - Any mutation / bulk action
 *   - Expanded action taxonomy (attach, export, etc.)
 *
 * Ownership boundaries:
 *   - Navigation → react-router `useNavigate()` (no hook indirection).
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
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { useLogout } from '../features/auth/useLogout'
import { SearchResultsSection } from '../features/search/SearchResultsSection'
import {
  COMMAND_IDS,
  getCommandKeywords,
  getCommandLabel,
  type CommandId,
} from '../lib/commands'
import { cn } from '../lib/utils'
import { useFilterStore } from '../stores/filters'

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
  // Palette-local ephemeral input — NEVER persisted to URL, local
  // storage, or the filter store. Closing the dialog resets it to
  // empty (see `useEffect` below), so reopening always starts fresh.
  // Plan D18 + OI4 carry: q does not touch the router / URL state.
  const [q, setQ] = useState('')
  const navigate = useNavigate()
  const clearFilters = useFilterStore((s) => s.clear)
  const logoutMutation = useLogout()
  // `useTranslation` subscribes this component to locale changes,
  // so switching ko↔en re-renders and re-resolves every
  // `getCommandLabel(id)` call below.
  const { t } = useTranslation()

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

  // Reset q when the dialog closes so the next open starts clean.
  // Prevents a stale query from carrying across palette opens and
  // keeps "q is ephemeral" a provable invariant.
  useEffect(() => {
    if (!open) setQ('')
  }, [open])

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

  function handleSelectSearchResult(reportId: number): void {
    // Mirrors the nav-command path — close the dialog first so the
    // exit transition starts, then navigate. Same rationale as
    // `runCommand` above.
    setOpen(false)
    navigate(`/reports/${reportId}`)
  }

  return (
    <>
      <button
        type="button"
        data-testid="cmdk-trigger"
        onClick={() => setOpen(true)}
        aria-label={t('shell.search.dialogLabel')}
        className={cn(
          'flex h-8 items-center gap-2 rounded border border-border-card bg-app px-3 text-xs text-ink-muted',
          'hover:border-signal hover:text-ink focus:outline-none focus:ring-2 focus:ring-signal',
        )}
      >
        <CommandIcon aria-hidden className="h-3 w-3" />
        <span>{t('shell.search.placeholder')}</span>
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
        label={t('shell.search.dialogLabel')}
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
            placeholder={t('shell.search.inputPlaceholder')}
            value={q}
            onValueChange={setQ}
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
              {t('shell.search.emptyLabel')}
            </Command.Empty>

            {COMMAND_IDS.map((id) => {
              const label = getCommandLabel(id)
              const keywords = getCommandKeywords(id)
              return (
                <Command.Item
                  key={id}
                  value={[id, label, ...keywords].join(' ')}
                  data-testid={`cmdk-item-${id}`}
                  onSelect={() => runCommand(id)}
                  className={cn(
                    'flex cursor-pointer items-center justify-between rounded px-4 py-2 text-sm',
                    'data-[selected=true]:bg-app',
                  )}
                >
                  <span>{label}</span>
                  <span className="text-[10px] uppercase tracking-wider text-ink-subtle">
                    {id}
                  </span>
                </Command.Item>
              )
            })}

            {/*
              PR #17 Group E — server-backed /search results. Lives
              as a sibling of the static `COMMAND_IDS.map(...)` above,
              NOT mixed into it (plan D3 scope lock). Renders null
              when q is empty, so the palette's no-query view is
              byte-identical to its pre-PR #17 appearance.
            */}
            <SearchResultsSection
              q={q}
              onSelectResult={handleSelectSearchResult}
            />
          </Command.List>
        </div>
      </Command.Dialog>
    </>
  )
}

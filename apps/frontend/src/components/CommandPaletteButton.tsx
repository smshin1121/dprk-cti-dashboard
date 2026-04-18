/**
 * Command palette trigger + empty dialog skeleton.
 *
 * PR #12 scope (plan D5 + §1 non-goals):
 *   - Trigger button with ⌘K visible hint in the topbar.
 *   - `mod+k` global keyboard shortcut (Cmd on macOS, Ctrl elsewhere).
 *   - Empty `cmdk` dialog with "coming soon" placeholder — NO search
 *     input, NO action list, NO route integration.
 *   - Escape closes.
 *
 * PR #13+ adds the actual search surface + action routes. Keeping
 * the skeleton shell-only here is intentional — the plan lists this
 * under §1 non-goals so the analyst can see where ⌘K is without
 * accidentally shipping a half-built command set.
 *
 * Shortcut capture discipline:
 * The keydown listener lives on `window` (not on the trigger button)
 * so the shortcut works from anywhere on the page. It early-exits
 * when focus is on an editable field (input/textarea/contenteditable)
 * so typing "K" while holding Ctrl in a date input, textarea, etc.
 * doesn't hijack the user's keystroke.
 */

import { Command } from 'cmdk'
import { Command as CommandIcon } from 'lucide-react'
import { useEffect, useState } from 'react'

import { cn } from '../lib/utils'

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

export function CommandPaletteButton(): JSX.Element {
  const [open, setOpen] = useState(false)

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
            'w-full max-w-lg rounded-lg border border-border-card bg-surface p-6 text-ink shadow-xl',
          )}
        >
          <p
            data-testid="cmdk-placeholder"
            className="text-center text-sm text-ink-muted"
          >
            Command palette — coming soon in PR #13. Press Esc to close.
          </p>
        </div>
      </Command.Dialog>
    </>
  )
}

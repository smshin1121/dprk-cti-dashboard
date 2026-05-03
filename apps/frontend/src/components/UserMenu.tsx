/**
 * Top-nav user menu.
 *
 * Dropdown composition:
 *   Header     — email + primary-role badge (identity affordance)
 *   Separator
 *   Language   — `LocaleToggle`
 *   Separator
 *   Logout     — triggers `useLogout` → `queryClient.clear()` (via
 *                hook's onSuccess) → local navigate('/login').
 *
 * Navigation ownership:
 * The useLogout hook explicitly does NOT navigate (its docstring
 * calls this out — navigation inside the hook would couple it to
 * react-router and force a router wrapper for unit tests). The
 * user-menu owns the post-logout navigation via `useNavigate()`.
 *
 * Invisible-when-unauth posture:
 * The Shell renders UserMenu only under RouteGate's authenticated
 * branch, so `useAuth().user` is always non-null here in practice.
 * A defensive `user == null → return null` branch keeps the
 * component robust to re-mount races during logout without adding
 * a route-level check.
 */

import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { ChevronDown, LogOut, UserCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../features/auth/useAuth'
import { useLogout } from '../features/auth/useLogout'
import { cn } from '../lib/utils'
import { LocaleToggle } from './LocaleToggle'

export function UserMenu(): JSX.Element | null {
  const { user } = useAuth()
  const logoutMutation = useLogout()
  const navigate = useNavigate()
  const { t } = useTranslation()

  if (user == null) return null

  function handleLogout(): void {
    logoutMutation.mutate(undefined, {
      onSuccess: () => navigate('/login'),
    })
  }

  const primaryRole = user.roles[0] ?? 'unknown'

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          data-testid="user-menu-trigger"
          aria-label={t('userMenu.triggerAriaLabel', { email: user.email })}
          className={cn(
            'flex h-8 items-center gap-2 rounded-none border border-border-card bg-app px-2 text-xs text-ink',
            'hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring',
          )}
        >
          <UserCircle aria-hidden className="h-4 w-4 text-ink-muted" />
          <span className="max-w-[10rem] truncate">{user.email}</span>
          <ChevronDown aria-hidden className="h-3 w-3 text-ink-subtle" />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          sideOffset={6}
          align="end"
          className={cn(
            'z-50 min-w-[14rem] rounded-none border border-border-card bg-surface p-1 text-xs text-ink shadow-lg',
          )}
        >
          <DropdownMenu.Label className="px-2 py-1.5">
            <div
              data-testid="user-menu-email"
              className="truncate font-medium text-ink"
            >
              {user.email}
            </div>
            <div
              data-testid="user-menu-role"
              className="mt-1 inline-flex items-center rounded-full border border-border-card bg-app px-1.5 py-0.5 text-[10px] font-cta uppercase tracking-caption text-ink-muted"
            >
              {primaryRole}
            </div>
          </DropdownMenu.Label>

          <DropdownMenu.Separator className="my-1 h-px bg-border-card" />

          <div className="flex items-center justify-between px-2 py-1.5">
            <span className="text-[10px] font-cta uppercase tracking-caption text-ink-subtle">
              {t('userMenu.language')}
            </span>
            <LocaleToggle />
          </div>

          <DropdownMenu.Separator className="my-1 h-px bg-border-card" />

          <DropdownMenu.Item
            data-testid="user-menu-logout"
            onSelect={(event) => {
              // Don't close the menu before the mutation fires —
              // Radix closes on select by default, but we let it run
              // because the navigate() happens on success and the
              // user is about to leave this route anyway.
              event.preventDefault()
              handleLogout()
            }}
            className={cn(
              'flex cursor-pointer items-center gap-2 rounded-none px-2 py-1.5 outline-none',
              'focus:bg-app data-[highlighted]:bg-app',
            )}
          >
            <LogOut aria-hidden className="h-3 w-3" />
            {t('userMenu.signOut')}
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

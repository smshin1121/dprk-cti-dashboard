/**
 * Auth UI state — zustand.
 *
 * ABSOLUTE SCOPE RULE (plan D10 lock):
 * This store holds UI state ONLY. The authenticated user's identity
 * lives in the React Query cache at `queryKeys.me()`. Do NOT add
 * `user: CurrentUser | null` to this store. Do NOT add `roles`.
 * Do NOT add `isAuthenticated`. All of those are derived from the
 * query cache via `useAuth()` (see features/auth/useAuth.ts).
 *
 * What belongs here: UI-only state the server doesn't know about.
 * Currently that is a single field — where the user was trying to
 * go when the guard bumped them to /login. After successful login,
 * `useMe.onSuccess` (or the login page `useEffect`) reads and
 * clears this value to complete the redirect.
 *
 * If anyone adds a `user` / `roles` / `isAuthenticated` field here
 * in the future, the PR reviewer's job is to bounce it — the
 * invariant this lock protects is "one source of truth per fact".
 */

import { create } from 'zustand'

export interface AuthUIState {
  /**
   * Path the user tried to reach before the auth gate redirected
   * them to /login. Populated by the route gate; consumed+cleared
   * by the post-login redirect effect.
   *
   * `null` means either no intent was recorded OR the intent has
   * already been consumed (equivalent semantically — a cleared
   * intent must not fire twice).
   */
  postLoginRedirect: string | null
  setPostLoginRedirect: (path: string | null) => void
  clearPostLoginRedirect: () => void
}

export const useAuthStore = create<AuthUIState>((set) => ({
  postLoginRedirect: null,
  setPostLoginRedirect: (path) => set({ postLoginRedirect: path }),
  clearPostLoginRedirect: () => set({ postLoginRedirect: null }),
}))

/**
 * ⌘K command registry — PR #13 plan D3 lock + D5 i18n bridge.
 *
 * This module is pure data + a label getter. No React hooks, no
 * component dependencies. It IS allowed to read from i18next because
 * i18next exposes a plain function (`i18n.t(...)`) — not a hook —
 * so the registry stays usable in non-React contexts (tests, future
 * workers) without importing React.
 *
 * Registry purity contract (Group C/D review criterion):
 *   - `COMMAND_IDS` is a stable `as const` tuple — the single source
 *     of truth for what the palette exposes.
 *   - `getCommandLabel(id)` / `getCommandKeywords(id)` are pure-ish
 *     functions: given the current i18next state, they return strings
 *     deterministically. Calling them does not mutate anything.
 *   - The component iterates `COMMAND_IDS` at render time and calls
 *     the getters there; locale change causes a re-render (via
 *     `useTranslation`) which re-resolves labels.
 *
 * Scope (plan D3 + Ferrari L1 — theme cycle removed when theme model
 * collapsed to single dark canvas):
 *   Navigate: /dashboard /reports /incidents /actors
 *   View:     clear filters
 *   Session:  sign out
 *
 * i18n swap (plan D5):
 * Labels route through `i18n.t('commands.${id}')`. The previous
 * hardcoded `LABELS` table is deleted — `ko.json` / `en.json` now
 * own the display strings. Keywords stay hardcoded English for the
 * fuzzy matcher; label already contains the translated words so
 * Korean input matches against label text directly.
 *
 * NOTE — no `COMMAND_DEFINITIONS` const:
 * The previous `.map(...)` construction evaluated `getCommandLabel`
 * at module load, which predated i18n initialization. Evaluating
 * labels at render time is the correct behaviour once `t()` is
 * involved — the getter is called per render under `useTranslation`
 * subscription, so locale changes flow through naturally.
 */

import i18n from '../i18n'

export const COMMAND_IDS = [
  'nav.dashboard',
  'nav.reports',
  'nav.incidents',
  'nav.actors',
  'filters.clear',
  'auth.logout',
] as const

export type CommandId = (typeof COMMAND_IDS)[number]

export interface CommandDefinition {
  id: CommandId
  label: string
  keywords: string[]
}

/** Keywords stay English — they're fuzzy-match hints, not the
 *  primary search target. The translated label is already in the
 *  cmdk `value` string so Korean / English text searches hit. */
const KEYWORDS: Record<CommandId, string[]> = {
  'nav.dashboard': ['navigate', 'go', 'home', 'kpi', 'overview'],
  'nav.reports': ['navigate', 'go', 'list', 'intel'],
  'nav.incidents': ['navigate', 'go', 'list', 'attacks'],
  'nav.actors': ['navigate', 'go', 'list', 'groups', 'apt'],
  'filters.clear': ['reset', 'clear', 'filters', 'date', 'group'],
  'auth.logout': ['logout', 'sign out', 'exit', 'session'],
}

export function getCommandLabel(id: CommandId): string {
  return i18n.t(`commands.${id}`)
}

export function getCommandKeywords(id: CommandId): string[] {
  return KEYWORDS[id]
}

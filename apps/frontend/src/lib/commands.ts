/**
 * ⌘K command registry — PR #13 plan D3 lock.
 *
 * This module is pure data + a label getter. It carries NO hook / store
 * / router dependencies, so it can be imported from tests, the
 * component, and future i18n wiring without pulling in React-runtime
 * context. The component that renders the palette
 * (`components/CommandPaletteButton.tsx`) owns the action wiring — it
 * imports these IDs + labels and maps each to a hook/store call.
 *
 * Scope (plan D3 lock — deliberately narrow):
 *   - nav.dashboard / nav.reports / nav.incidents / nav.actors
 *   - theme.cycle
 *   - filters.clear
 *   - auth.logout
 *
 * Explicitly excluded (plan D3 + §1 non-goals):
 *   - Full-text search across reports / incidents / actors data
 *   - Server-backed search
 *   - Bulk or mutation actions (anything that creates/updates/deletes)
 *
 * i18n preparation (Group F):
 * Labels are stored here as the single source of truth for display
 * strings. The getCommandLabel() indirection means Group F can swap
 * the implementation to `t(command.labelKey)` without touching the
 * component or tests' command-ID assertions. Tests that check labels
 * use the getter so they automatically align with the i18n source
 * once Group F lands.
 */

export const COMMAND_IDS = [
  'nav.dashboard',
  'nav.reports',
  'nav.incidents',
  'nav.actors',
  'theme.cycle',
  'filters.clear',
  'auth.logout',
] as const

export type CommandId = (typeof COMMAND_IDS)[number]

export interface CommandDefinition {
  id: CommandId
  /**
   * Display label. Today returned verbatim from the module-local
   * table. Group F will route this through `react-i18next.t(...)`
   * using the command id as the translation key. The component does
   * not re-hardcode any of these strings.
   */
  label: string
  /**
   * Additional words cmdk's fuzzy matcher should index for this
   * command. Helps with "nav" / "go" / "jump" style searches even
   * though they don't appear in the visible label.
   */
  keywords: string[]
}

/**
 * Labels map — single point of change for Group F i18n. The
 * component reads through `getCommandLabel(id)` so replacing this
 * table with a call to `t(...)` is a one-line edit.
 */
const LABELS: Record<CommandId, string> = {
  'nav.dashboard': 'Go to Dashboard',
  'nav.reports': 'Go to Reports',
  'nav.incidents': 'Go to Incidents',
  'nav.actors': 'Go to Actors',
  'theme.cycle': 'Cycle theme (light / dark / system)',
  'filters.clear': 'Clear all filters',
  'auth.logout': 'Sign out',
}

const KEYWORDS: Record<CommandId, string[]> = {
  'nav.dashboard': ['navigate', 'go', 'home', 'kpi', 'overview'],
  'nav.reports': ['navigate', 'go', 'list', 'intel'],
  'nav.incidents': ['navigate', 'go', 'list', 'attacks'],
  'nav.actors': ['navigate', 'go', 'list', 'groups', 'apt'],
  'theme.cycle': ['appearance', 'dark', 'light', 'system', 'mode'],
  'filters.clear': ['reset', 'clear', 'filters', 'date', 'group'],
  'auth.logout': ['logout', 'sign out', 'exit', 'session'],
}

export function getCommandLabel(id: CommandId): string {
  return LABELS[id]
}

export function getCommandKeywords(id: CommandId): string[] {
  return KEYWORDS[id]
}

/**
 * Static command metadata list. Order is the default display order in
 * the palette when the user hasn't typed a filter. Navigation commands
 * first (most frequent action class), then view-affecting commands
 * (theme, clear filters), then destructive/session (sign out).
 */
export const COMMAND_DEFINITIONS: readonly CommandDefinition[] = COMMAND_IDS.map(
  (id) => ({ id, label: getCommandLabel(id), keywords: getCommandKeywords(id) }),
)

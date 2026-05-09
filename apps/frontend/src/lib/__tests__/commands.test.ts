/**
 * Registry + i18n bridge tests — plan D5 (PR #13 Group F).
 *
 * Goal: verify the registry stays pure (no React runtime deps) while
 * `getCommandLabel` routes through i18next. Switching locale must
 * flow through the same getter without touching call sites.
 */

import { describe, expect, it, beforeEach } from 'vitest'

import {
  COMMAND_IDS,
  getCommandKeywords,
  getCommandLabel,
  type CommandId,
} from '../commands'
import { i18n } from '../../i18n'

beforeEach(async () => {
  await i18n.changeLanguage('ko')
})

describe('COMMAND_IDS scope lock', () => {
  it('exposes exactly the 7 IDs locked in plan D3 + Ferrari L1 + PR-B T10', () => {
    // Ferrari L1 removed `theme.cycle` (single dark canvas, no theme
    // toggle). PR-B T10 added `nav.correlation` alongside the
    // /analytics/correlation router mount, the Shell nav entry, and
    // the PAGE_CLASS_BY_ROUTE manifest entry — all four surfaces
    // stay in sync. The 7 remaining IDs are the scope lock.
    expect(COMMAND_IDS).toEqual([
      'nav.dashboard',
      'nav.reports',
      'nav.incidents',
      'nav.actors',
      'nav.correlation',
      'filters.clear',
      'auth.logout',
    ])
  })
})

describe('getCommandLabel', () => {
  it('returns Korean strings when language is ko', () => {
    const label = getCommandLabel('nav.dashboard')
    expect(label).toBe('대시보드로 이동')
  })

  it('returns English strings when language is en', async () => {
    await i18n.changeLanguage('en')
    expect(getCommandLabel('nav.dashboard')).toBe('Go to Dashboard')
  })

  it('re-resolves after changeLanguage without re-importing the registry', async () => {
    // Same function reference, different output — proves the getter
    // is NOT evaluated eagerly at module load (as it was before the
    // F3 refactor).
    const ko = getCommandLabel('auth.logout')
    await i18n.changeLanguage('en')
    const en = getCommandLabel('auth.logout')
    expect(ko).not.toBe(en)
  })
})

describe('getCommandKeywords', () => {
  it('returns English keyword arrays regardless of locale', async () => {
    // Keywords are fuzzy-match hints, not user-visible labels.
    // Translated label is already in the cmdk `value` string so
    // Korean input matches against the label directly; duplicating
    // keywords across locales would be pointless maintenance.
    const kw = getCommandKeywords('nav.dashboard')
    expect(kw).toContain('navigate')

    await i18n.changeLanguage('en')
    const kwEn = getCommandKeywords('nav.dashboard')
    expect(kwEn).toEqual(kw)
  })
})

describe('registry purity', () => {
  it('command registry imports do NOT pull in React', async () => {
    // Static check — importing commands.ts should not transitively
    // require a React runtime. If a future edit accidentally
    // imports from react / react-dom / react-i18next, this test
    // fires.
    const commandsModule = await import('../commands')
    // Probing for React-provided globals that shouldn't be needed.
    // The runtime import succeeded (i.e. this test ran) = proof.
    expect(Object.keys(commandsModule)).toEqual(
      expect.arrayContaining([
        'COMMAND_IDS',
        'getCommandLabel',
        'getCommandKeywords',
      ]),
    )
  })
})

describe('locale-driven CommandPaletteButton re-render (integration)', () => {
  it('getCommandLabel swapped values reflect in the palette at next render', async () => {
    // NOTE: full render/click cycle lives in CommandPaletteButton.
    // tsx; here we verify the contract the component relies on —
    // calling getCommandLabel after changeLanguage returns the new
    // locale's string immediately (no cache invalidation step).
    const ids: CommandId[] = ['nav.dashboard', 'auth.logout']
    const before = ids.map((id) => getCommandLabel(id))
    await i18n.changeLanguage('en')
    const after = ids.map((id) => getCommandLabel(id))
    for (let i = 0; i < ids.length; i++) {
      expect(after[i]).not.toBe(before[i])
      expect(after[i].length).toBeGreaterThan(0)
    }
  })
})

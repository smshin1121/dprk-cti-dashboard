/**
 * DESIGN.md Dashboard KPI Compact Variant amendment — RED static-source test.
 * PR 2.5 T5.
 *
 * Mirrors the T5 static-source guard pattern from PR #33
 * (Shell.architectural-guard.test.tsx) — read DESIGN.md from disk
 * via fs.readFileSync and grep for the new section anchor +
 * mandatory token recipe + cross-reference from the existing
 * `## Dashboard Workspace Pattern` section.
 *
 * Contract per `docs/plans/dashboard-kpi-density.md` L11:
 *   - DESIGN.md MUST add a top-level section heading exactly
 *     `## Dashboard KPI Compact Variant`.
 *   - Section MUST cite the new compact typography token (text-3xl
 *     ~30px) AND explicitly differentiate from the locked 80px
 *     `## Spec & Race Surfaces` pattern.
 *   - Section MUST be cross-referenced from the existing
 *     `## Dashboard Workspace Pattern > Center-Pane Widget Surfaces`
 *     section (so a reader scanning the workspace pattern is pointed
 *     at the compact variant).
 *
 * RED phase: DESIGN.md does NOT yet contain the new section. T6
 * GREEN adds it.
 */

import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

// DESIGN.md sits at the repo root, three levels above this test file:
//   apps/frontend/src/features/dashboard/__tests__/<this>
//   → apps/frontend/src/features/dashboard
//   → apps/frontend/src/features
//   → apps/frontend/src
//   → apps/frontend
//   → apps
//   → repo root
const DESIGN_MD_PATH = path.resolve(__dirname, '../../../../../../DESIGN.md')

describe('DESIGN.md — Dashboard KPI Compact Variant amendment (PR 2.5 T5/L11)', () => {
  it('DESIGN.md is readable from this test', () => {
    expect(fs.existsSync(DESIGN_MD_PATH)).toBe(true)
  })

  it('contains the new top-level section heading exactly', () => {
    const text = fs.readFileSync(DESIGN_MD_PATH, 'utf8')
    expect(text).toMatch(/^## Dashboard KPI Compact Variant$/m)
  })

  it('compact section explicitly cites the dashboard scope (NOT replacing the global Spec & Race Surfaces lock)', () => {
    const text = fs.readFileSync(DESIGN_MD_PATH, 'utf8')
    // Locate the Dashboard KPI Compact Variant section body — from
    // its heading to the next top-level (## ) heading.
    const sectionMatch = text.match(
      /^## Dashboard KPI Compact Variant$([\s\S]*?)(?=^## )/m,
    )
    expect(sectionMatch).not.toBeNull()
    const section = sectionMatch![1]
    // Must mention the compact typography token (text-3xl OR a
    // typography token name pointing at ~30px).
    expect(section).toMatch(/text-3xl|30px/i)
    // Must reference the global Spec & Race Surfaces lock so a
    // reviewer can see the amendment is additive, not a revision.
    expect(section).toMatch(/Spec & Race Surfaces|spec-cell/i)
    // Must scope the variant to /dashboard explicitly.
    expect(section).toMatch(/\/dashboard/)
  })

  it('compact section cites the optional delta indicator + sparkline slots', () => {
    const text = fs.readFileSync(DESIGN_MD_PATH, 'utf8')
    const sectionMatch = text.match(
      /^## Dashboard KPI Compact Variant$([\s\S]*?)(?=^## )/m,
    )
    expect(sectionMatch).not.toBeNull()
    const section = sectionMatch![1]
    expect(section).toMatch(/delta/i)
    expect(section).toMatch(/sparkline/i)
  })

  it('## Dashboard Workspace Pattern section cross-references the new variant', () => {
    const text = fs.readFileSync(DESIGN_MD_PATH, 'utf8')
    const workspaceSectionMatch = text.match(
      /^## Dashboard Workspace Pattern$([\s\S]*?)(?=^## )/m,
    )
    expect(workspaceSectionMatch).not.toBeNull()
    const workspaceSection = workspaceSectionMatch![1]
    // The kpi-strip vocabulary entry (or somewhere in the section)
    // must point at the new compact variant section.
    expect(workspaceSection).toMatch(/Dashboard KPI Compact Variant/)
  })
})

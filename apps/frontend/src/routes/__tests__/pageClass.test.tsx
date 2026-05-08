/**
 * Page-class manifest bidirectional sync — static-source assertion
 * (PR-B T0). Mirrors the regression-guard pattern used by
 * `Shell.architectural-guard.test.tsx`: read source files at test
 * time, grep-style assert the contract.
 *
 * Three invariants pinned here:
 *
 *   1. **Manifest ≡ router** — the set of paths in
 *      `PAGE_CLASS_BY_ROUTE` matches the set of `path: '...'` literals
 *      mounted in `router.tsx`. Drift in either direction fails:
 *      adding a new route without manifest entry fails the test, and
 *      adding a manifest entry without a real route also fails.
 *
 *   2. **Attribute presence** — for each manifest entry, the mapped
 *      component file's source contains the literal
 *      `data-page-class="<class>"` matching its taxonomy. The
 *      attribute lives on the populated render branch of each route
 *      container (transient loading / error panels are not part of
 *      the page-class contract).
 *
 *   3. **Cardinality** — exactly 9 entries pre-T10 (T10 of the same
 *      PR adds `/analytics/correlation`, bringing the total to 10
 *      before merge).
 *
 * Static-source rather than DOM render so the contract holds without
 * mocking 6 detail/list page queries. Runtime CSS hookup of
 * `[data-page-class="..."]` selectors is exercised separately by the
 * design-system style sheets and the umbrella plan's hardening PR.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { PAGE_CLASS_BY_ROUTE } from '../../lib/pageClass'

const SRC_ROOT = resolve(__dirname, '..', '..')
const ROUTER_PATH = resolve(SRC_ROOT, 'routes', 'router.tsx')

/**
 * Test-only metadata: which file owns the `data-page-class` literal
 * for each manifest route. The wildcard `*` route's NotFound
 * component is inlined inside `router.tsx`, so it points back to the
 * router file rather than to a separate page component.
 */
const ROUTE_TO_SOURCE_FILE: Record<keyof typeof PAGE_CLASS_BY_ROUTE, string> = {
  '/login': 'routes/LoginPage.tsx',
  '/dashboard': 'routes/DashboardPage.tsx',
  '/reports': 'routes/ReportsPage.tsx',
  '/reports/:id': 'routes/ReportDetailPage.tsx',
  '/incidents': 'routes/IncidentsPage.tsx',
  '/incidents/:id': 'routes/IncidentDetailPage.tsx',
  '/actors': 'routes/ActorsPage.tsx',
  '/actors/:id': 'routes/ActorDetailPage.tsx',
  '*': 'routes/router.tsx',
}

/**
 * Extract every `path: '...'` literal from `router.tsx`. The router's
 * tree mounts top-level routes with absolute paths (e.g. `/login`)
 * and nested routes inside `<Shell>` with relative paths (e.g.
 * `dashboard`, `reports/:id`); normalise everything to the absolute
 * form used by the manifest. Index routes (`{ index: true, ... }`)
 * have no `path:` key and are correctly excluded — the index `/`
 * redirect is not a routed page (DESIGN.md line 404).
 */
function extractRouterPaths(): string[] {
  const source = readFileSync(ROUTER_PATH, 'utf-8')
  const matches = source.matchAll(/path:\s*['"]([^'"]+)['"]/g)
  const paths: string[] = []
  for (const match of matches) {
    const raw = match[1]
    if (raw === '*' || raw.startsWith('/')) {
      paths.push(raw)
    } else {
      paths.push(`/${raw}`)
    }
  }
  return paths
}

describe('pageClass manifest — bidirectional sync', () => {
  it('manifest keys exactly match the paths mounted in router.tsx', () => {
    const routerPaths = [...extractRouterPaths()].sort()
    const manifestKeys = Object.keys(PAGE_CLASS_BY_ROUTE).sort()
    expect(routerPaths).toEqual(manifestKeys)
  })

  it.each(Object.entries(PAGE_CLASS_BY_ROUTE))(
    'route %s — owning file declares data-page-class="%s"',
    (route, expectedClass) => {
      const file = ROUTE_TO_SOURCE_FILE[route as keyof typeof PAGE_CLASS_BY_ROUTE]
      const source = readFileSync(resolve(SRC_ROOT, file), 'utf-8')
      const literal = `data-page-class="${expectedClass}"`
      expect(
        source.includes(literal),
        `${file} must contain the literal ${literal} on the route container for ${route}.`,
      ).toBe(true)
    },
  )

  it('manifest holds exactly 9 entries pre-T10 (T10 adds /analytics/correlation → 10)', () => {
    expect(Object.keys(PAGE_CLASS_BY_ROUTE).length).toBe(9)
  })
})

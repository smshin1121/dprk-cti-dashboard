/**
 * Page-class runtime taxonomy (PT-7 hookup for the design contract
 * locked in PR #31). DESIGN.md `## Page Classes` (lines 320-326) names
 * five semantic classes; `## Page Classes Mapping` (lines 403-412)
 * pins each currently-routed FE path to its class. This module is the
 * machine-readable mirror of that table.
 *
 * Each manifested route container carries a matching `data-page-class`
 * attribute on its outermost render so the design system can target
 * page-class-specific styling via `[data-page-class="..."]` selectors
 * at runtime. The bidirectional sync test in
 * `apps/frontend/src/routes/__tests__/pageClass.test.tsx` enforces:
 *   - manifest keys ≡ paths actually mounted in `router.tsx`
 *   - each mapped component's source contains the attribute literal
 *
 * The index `/` route (which redirects to `/dashboard`) is excluded —
 * not a routed page; the destination page's class wins. `/search` is
 * also excluded — its FE feature directory exists but no route is
 * mounted (DESIGN.md line 411).
 *
 * The `/analytics/correlation` entry was added by T10 of PR-B (D-1
 * correlation FE), bringing the manifest count to 10. The route
 * mounts `CorrelationPage`, whose outermost `<section>` declares
 * `data-page-class="analyst-workspace"` (T9 wired the attribute;
 * T10 appended the manifest entry + router mount + nav + palette
 * entries simultaneously to keep the bidirectional sync test green).
 */

export type PageClass =
  | 'editorial-page'
  | 'auth-page'
  | 'analyst-workspace'
  | 'admin-workspace'
  | 'system-page'

export const PAGE_CLASS_BY_ROUTE = {
  '/login': 'auth-page',
  '/dashboard': 'analyst-workspace',
  '/reports': 'analyst-workspace',
  '/reports/:id': 'analyst-workspace',
  '/incidents': 'analyst-workspace',
  '/incidents/:id': 'analyst-workspace',
  '/actors': 'analyst-workspace',
  '/actors/:id': 'analyst-workspace',
  '/analytics/correlation': 'analyst-workspace',
  '*': 'system-page',
} as const satisfies Record<string, PageClass>

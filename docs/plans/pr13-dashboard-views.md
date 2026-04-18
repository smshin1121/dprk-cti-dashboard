# PR #13 — Phase 2.4 Dashboard Views (Visualizations + URL State + i18n)

**Status:** 🔒 **Locked** — D1–D9 frozen 2026-04-18 after 1-round discuss-phase (six §2.1 open items resolved, no candidate reversals). Execution starts with Group A on branch `feat/p2.4-dashboard-views`.

**Branch target:** `feat/p2.4-dashboard-views` (created 2026-04-18, off `main` at `1722719`).

**Base:** `main` at merge commit `1722719` (PR #12 FE shell — filter bar + KPI strip + list routes + user menu + ⌘K trigger + Pact consumer + live contract-verify + Playwright E2E).

---

## 1. Goal

Ship the **dashboard visualizations layer** that plugs into the PR #12 shell — design doc v2.0 §4.2 areas **[C] world map**, **[D] ATT&CK heatmap + donut + bar**, **[E] trend + groups + feed + Similar Reports**, **[F] alerts drawer content**. Also lands the three Phase 2 W6 close-out items: **⌘K command content**, **URL-state sync** for shareable filters/views, and **i18n (ko/en)** for analyst-facing copy.

Mapping to v2.0 §14 roadmap: **Phase 2 W3–W6**. This PR is the milestone-M2 exit candidate — Lighthouse target ≥ 90 (D6) is the manual acceptance artifact.

Concrete deliverables (draft):

1. **BE:** minimal read-only `/api/v1/analytics/*` endpoints — `attack_matrix`, `trend`, `geo` (D2). Pydantic DTOs + OpenAPI snapshot update + unit/integration/contract tests.
2. **FE [C]:** world map with country-aggregate overlay + DPRK highlight (D7).
3. **FE [D]:** ATT&CK tactic × technique heatmap (top-N filter, D8) + motivation donut + year bar.
4. **FE [E]:** time-series trend chart + groups mini-list + report feed + Similar Reports panel.
5. **FE [F]:** alerts drawer content (static shell + empty state; real-time fetch still Phase 4).
6. **FE ⌘K command content:** navigation commands + theme toggle + clear filters (D3).
7. **FE URL-state sync:** date range + group ids + dashboard subview/tab in URL (D4).
8. **FE i18n:** ko/en for shell labels + chart titles + empty/error copy (D5).
9. **Lighthouse ≥ 90** across Performance / Accessibility / Best Practices / SEO — manual PR artifact (D6).

Explicit non-goals (deferred):

- TLP in URL state → out of scope (D4)
- Backend domain-value translation (actor names, MITRE technique names) → out of scope (D5)
- Alerts real-time fetch / WebSocket / SSE → Phase 4
- Detail views (`/reports/:id`, `/incidents/:id`, `/actors/:id`) → Phase 3
- ⌘K full-text / server-backed search → Phase 3+ (D3)
- Korea-specific map projection → out of scope (D7)
- Full ATT&CK matrix render (all ~600 techniques) → out of scope (D8)

---

## 2. Decisions — Lock Candidates (D1–D9)

Locked 2026-04-18 after 1-round user review. Draft v1 D1–D9 candidates adopted on core positions; six §2.1 open items resolved by extending table detail (no candidate reversals). Lock commit = `docs(plan): lock PR #13 dashboard views plan` on `feat/p2.4-dashboard-views`.

| ID | Item | Draft v1 Candidate | Rationale |
|:---:|:---|:---|:---|
| **D1** | Viz library | **`@visx/visx` + `d3` core.** `visx` for scales/axes/geo/shapes; `d3-scale` / `d3-geo` / `topojson-client` for raw math. NOT recharts. | `@visx/visx` + `topojson-client` are already in deps (PR #12). Map + ATT&CK heatmap + custom tooltip / legend control need primitives, not recharts' opinionated wrappers. |
| **D2** | `/analytics` BE scope | **Include in this PR.** Three minimal read-only endpoints: `GET /api/v1/analytics/attack_matrix`, `GET /api/v1/analytics/trend`, `GET /api/v1/analytics/geo`. All respect the same `date_from` / `date_to` / `group_id[]` filter contract as `/dashboard/summary`. **Rate limit: 60/min per-user** (same slowapi tier as PR #11 read endpoints). **Response shapes (locked):** `attack_matrix` = row-based by tactic — `{ tactics: TacticRef[], rows: { tactic_id, techniques: { technique_id, count }[] }[] }`; `trend` = monthly buckets — `{ buckets: { month: "YYYY-MM", count }[] }`; `geo` = plain country aggregate — `{ countries: { iso2, count }[] }` (no DPRK special-case field; FE handles highlight per D7). | Static fixtures would gut Phase 2.4's value. Read-only + same limit tier keeps analyst UX consistent with PR #11. Row-based matrix simplifies FE render vs sparse-cells list; monthly buckets match dashboard readability; DPRK handled client-side keeps BE contract neutral across geographies. |
| **D3** | ⌘K scope | **Navigation commands only.** Include: go to `/dashboard` / `/reports` / `/incidents` / `/actors`, theme toggle, clear filters, sign out. Exclude: full-text search, server-backed search, bulk actions. | Natural extension of PR #12's placeholder. Server-backed search is Phase 3+ once detail routes exist. Fewer moving parts = fewer regressions. |
| **D4** | URL-state sync scope | **Filters + selected view/tab only.** Include: `date_from`, `date_to`, `group_id[]`, dashboard `view`/`tab` (e.g., `?view=actors&tab=overview`). Exclude: TLP, pagination cursor stack, dialog-open state, hover, ⌘K open. | Only shareable / reproducible state belongs in the URL. Ephemeral UI state polluting URLs causes back-button surprises. TLP stays client-only (PR #12 D5 lock carries forward). |
| **D5** | i18n scope + lib | **Library: `react-i18next` + `i18next-browser-languagedetector`. Default locale: `ko`. Manual toggle in UserMenu beside ThemeToggle** (detected locale overridable). Translated surface: shell labels + chart titles + empty/error copy + ⌘K command labels. Exclude: BE domain values (actor names, MITRE technique / tactic names, group aliases), analyst-entered free text. | User-facing chrome is closed surface; BE domain values are authoritative data (translating creates drift). `react-i18next` battle-tested + lightweight; `lingui` / `formatjs` overkill at this scope. Korean default matches primary analyst base; browser detection + manual toggle handles override. |
| **D6** | Lighthouse gate | **Manual PR acceptance artifact, NOT CI hard gate.** Targets: Performance / Accessibility / Best Practices / SEO all ≥ 90 on `/dashboard` (light + dark). Reported in PR body as Lighthouse report artifact. | Headless Lighthouse in CI is flaky (variance ±10 points on shared runners). Product wiring is the priority this milestone; enforcement comes once measurements stabilize. M2 exit gate = reviewer confirmation of artifact, not red/green CI. |
| **D7** | Map projection / scope / asset | **World map (Natural Earth projection) with DPRK highlight + country-aggregate overlay. TopoJSON bundled as static asset** (`apps/frontend/src/assets/topojson/world-110m.json`, ~30 KB gzipped); **no CDN dependency.** NOT a Korea-peninsula-specific projection. | DPRK threat-actor activity is global; world projection is right frame. Bundled asset keeps Lighthouse + offline CI + reproducibility sound; CDN fetch adds blocking-paint risk for no gain. `visx/geo` + `topojson-client` + Natural Earth 110m = standard stack. |
| **D8** | ATT&CK heatmap granularity + empty UX | **Tactic × technique count matrix, initial render = top-N observed techniques only (default N=30).** User can expand to full observed set via a toggle; rare-technique tail is collapsible. **Empty-matrix UX: dedicated empty-state card** ("No ATT&CK activity for current filters" + clear-filters CTA), NOT a collapsed heatmap overlay. | Rendering all ~600 MITRE techniques hurts perf and readability. Top-N by observed count surfaces what's relevant for DPRK CTI. Empty card beats collapsed overlay — overlay wobbles layout and has weak explanation; card has clear copy + recovery action. |
| **D9** | Data fetching / caching | **React-Query (carried from PR #12). Viz endpoints as separate queries — one query per chart. URL-state participates in query keys.** `useAttackMatrix(filters)`, `useTrend(filters)`, `useGeo(filters)`. TLP excluded from keys (D4 consistency). | Mirrors PR #12 Group E pattern (primitive-field selectors) — TLP toggle never refetches. URL-state → query-key binding makes shareable URLs replay-stable. Per-chart queries keep error/loading boundaries local; a chart fetch failure degrades one panel, not the whole dashboard. |

### 2.1 Revision log

Draft v1 (D1–D9 candidates) adopted verbatim on core positions. Discuss-phase round 1 (2026-04-18) resolved six open items by extending table detail — no candidate reversals:

- **D2 response shapes** — `attack_matrix` row-based by tactic (`tactics[] + rows[]` with nested `techniques[]`); `trend` monthly buckets (`YYYY-MM`); `geo` plain country aggregates (no DPRK special-case field — FE handles highlight per D7)
- **D2 rate limit** — 60/min per-user (same slowapi tier as PR #11 read)
- **D5 library** — `react-i18next` + `i18next-browser-languagedetector`
- **D5 default locale** — `ko` (with browser detection + manual toggle in UserMenu)
- **D7 TopoJSON** — bundled static asset at `apps/frontend/src/assets/topojson/world-110m.json` (no CDN)
- **D8 empty-matrix UX** — dedicated empty-state card ("No ATT&CK activity for current filters" + clear-filters CTA), not a collapsed overlay

---

## 3. Scope

### In scope (new files / major edits)

**BE `/analytics` (D2):**
- `services/api/src/api/routers/analytics.py` — 3 endpoints
- `services/api/src/api/schemas/analytics.py` — Pydantic DTOs (`AttackMatrixResponse`, `TrendResponse`, `GeoResponse`)
- `services/api/src/api/services/analytics/` — aggregation queries (SQL or SQLAlchemy ORM)
- `services/api/src/api/main.py` — router mount
- `services/api/tests/unit/test_analytics_*.py` — per-endpoint unit tests
- `services/api/tests/integration/test_analytics_endpoints.py` — live PG
- `services/api/tests/contract/test_pact_producer.py` — extend with 3 new `.given(...)` states
- `services/api/src/api/routers/pact_states.py` — 3 new state handlers (reuse `_ensure_full_group` / `_ensure_incident_with_motivation` helpers from PR #12)
- `contracts/openapi/openapi.json` — regenerated snapshot

**FE viz (D1, D7, D8):**
- `apps/frontend/src/lib/api/schemas.ts` — Zod for new analytics responses
- `apps/frontend/src/lib/api/endpoints.ts` — `getAttackMatrix`, `getTrend`, `getGeo`
- `apps/frontend/src/features/analytics/useAttackMatrix.ts`, `useTrend.ts`, `useGeo.ts`
- `apps/frontend/src/features/dashboard/WorldMap.tsx` — [C] area
- `apps/frontend/src/features/dashboard/AttackHeatmap.tsx` — [D] area, primary
- `apps/frontend/src/features/dashboard/MotivationDonut.tsx`, `YearBar.tsx` — [D] area, sub
- `apps/frontend/src/features/dashboard/TrendChart.tsx` — [E] area
- `apps/frontend/src/features/dashboard/GroupsMiniList.tsx`, `ReportFeed.tsx`, `SimilarReports.tsx` — [E] area
- `apps/frontend/src/features/dashboard/AlertsDrawer.tsx` — [F] area (static shell + empty state)
- `apps/frontend/src/assets/topojson/world-110m.json` — Natural Earth, bundled static

**FE ⌘K content (D3):**
- `apps/frontend/src/components/CommandPalette.tsx` — actual dialog content (expand PR #12 skeleton)
- `apps/frontend/src/lib/commands.ts` — command registry (navigate / theme / clearFilters / logout)

**FE URL-state sync (D4):**
- `apps/frontend/src/lib/urlState.ts` — encode/decode filter + view to/from URLSearchParams
- `apps/frontend/src/stores/filters.ts` — extend with URL-sync hook (useFilterUrlSync)
- `apps/frontend/src/routes/DashboardPage.tsx` — consume view/tab from URL

**FE i18n (D5):**
- `apps/frontend/src/i18n/` — init + ko.json + en.json
- `apps/frontend/src/i18n/index.ts` — `initI18n()` bootstrap
- `apps/frontend/src/main.tsx` — invoke `initI18n()` before render
- Touch existing copy in Shell / FilterBar / KPICard / ListTable / UserMenu to use `t('…')`

**Lighthouse (D6):**
- `apps/frontend/lighthouse/` — config + manual-run script
- PR body template — embed 4-score summary + artifact link

**Contract + tests:**
- `apps/frontend/tests/contract/frontend-dprk-cti-api.pact.test.ts` — extend pact consumer with 3 analytics interactions
- `apps/frontend/src/**/__tests__/*.test.ts` — vitest per new component/hook
- `apps/frontend/tests/integration/*.test.tsx` — MSW-backed for filter→chart refetch + URL-state replay
- `apps/frontend/tests/e2e/` — optional: extend D9 journey with a dashboard-view deep-link (URL-state replay)

**CI:**
- `.github/workflows/ci.yml` — no new jobs expected; existing `frontend` + `frontend-e2e` + `contract-verify` + `api-tests` + `api-integration` absorb the additions

**Deps (pnpm add — frozen list draft):**
- `@visx/geo`, `@visx/scale`, `@visx/axis`, `@visx/shape`, `@visx/tooltip`, `@visx/legend`, `@visx/heatmap` (visx peer pieces)
- `d3-scale`, `d3-array`, `d3-geo` (if not transitively covered)
- `topojson-client` (already present — verify)
- `react-i18next`, `i18next`, `i18next-browser-languagedetector`
- `qs` (URL state encoding) — evaluate vs hand-rolled

### Out of scope (explicit)

- TLP in URL state → stays client-only
- Alerts real-time fetch / WebSocket / SSE → Phase 4
- Detail views → Phase 3
- ⌘K full-text / server-backed search → Phase 3+
- Korea-specific map projection → out of scope
- Full ATT&CK matrix render → out of scope
- Backend domain-value translation → out of scope
- Lighthouse CI hard gate → manual artifact only (D6)
- OpenAPI → Zod codegen script (carried from PR #12 D7 defer) → standalone tooling PR
- `rejected → pending` admin reopen → carried follow-up
- `review.approval_rate` DQ metric → carried follow-up

---

## 4. Execution order (Groups)

Post-D-lock dependency chain. Each group = one commit on `feat/p2.4-dashboard-views`; all tests green before the next starts.

1. **Group A — BE `/analytics` endpoints (D2).** Three endpoints + Pydantic DTOs + aggregation queries + unit + integration tests. OpenAPI snapshot regenerated. No FE touch.
2. **Group B — BE pact provider-state extension.** 3 new `.given(...)` handlers in `pact_states.py` + provider-side contract tests. Reuses PR #12 Group I fixture helpers. No FE touch yet.
3. **Group C — FE analytics client layer.** Zod schemas + endpoints + `useAttackMatrix` / `useTrend` / `useGeo` hooks with primitive-field selectors (D9). Vitest unit only; MSW-backed integration for filter-key stability. Depends on A (OpenAPI snapshot).
4. **Group D — FE ⌘K command content (D3).** Expand PR #12 `CommandPaletteButton` skeleton → real `CommandPalette` with navigate / theme / clearFilters / logout. Unit tests per command. Independent of C.
5. **Group E — FE URL-state sync (D4).** `urlState.ts` encode/decode + `useFilterUrlSync` hook wired into FilterBar + DashboardPage. Integration test: change filter → URL updates; deep-link URL → filter store hydrated. Depends on nothing upstream in this PR; runs parallel with C + D.
6. **Group F — FE i18n (D5).** `react-i18next` init + ko.json + en.json + touch existing shell/filter copy. Vitest: locale switch re-renders translated labels. Independent; runs parallel with C / D / E.
7. **Group G — FE World Map viz [C] (D7).** `WorldMap.tsx` using `@visx/geo` + bundled TopoJSON + `useGeo`. DPRK highlight layer. Tooltip + legend. Unit + integration tests. Depends on C.
8. **Group H — FE ATT&CK heatmap [D] (D8).** `AttackHeatmap.tsx` (top-N default 30, toggle for full observed set) + `MotivationDonut.tsx` + `YearBar.tsx`. All use `useAttackMatrix` or `useDashboardSummary`. Depends on C.
9. **Group I — FE bottom row [E] + alerts drawer [F].** `TrendChart` + `GroupsMiniList` + `ReportFeed` + `SimilarReports` + `AlertsDrawer`. Depends on C; `SimilarReports` may touch `/reports` list hook (PR #12 Group F).
10. **Group J — Pact consumer extension + E2E deep-link.** Extend `frontend-dprk-cti-api.pact.test.ts` with 3 analytics interactions (attack_matrix / trend / geo happy). Optional: extend Playwright D9 journey with a URL-state deep-link assertion. Depends on A + B + C.
11. **Group K — Lighthouse manual run (D6).** Run `pnpm exec lighthouse http://localhost:4173/dashboard` against preview build, light + dark; attach JSON reports to PR. No CI change. Depends on G + H + I.

**Parallelism after lock commit:** A → B sequential. Then C is sequential-first on FE. D / E / F run in parallel with C. G / H / I wait for C. J waits for C + A + B. K is last.

---

## 5. Acceptance tests

### 5.1 Unit (vitest + RTL; BE pytest)

- BE `/analytics/attack_matrix`: row-based response shape (`tactics[] + rows[]` with nested techniques), top-N ordering correct, respects filters, returns empty-but-well-formed payload on zero-result filter
- BE `/analytics/trend`: monthly bucket aggregation (`YYYY-MM`) matches expected (fixture-pinned), respects `date_from` / `date_to`
- BE `/analytics/geo`: country-iso2 aggregation correct, DPRK returned as a plain country row (no special-case field — FE handles highlight per D7 + D2 lock)
- BE rate limit: `/analytics/*` all enforce 60/min per-user (same tier as PR #11 read)
- FE Zod schemas parse OpenAPI example payloads without error (pins BE snapshot drift, mirrors PR #12 pattern)
- FE `useAttackMatrix` / `useTrend` / `useGeo` subscribe to primitive filter fields only (TLP toggle does NOT refetch) — one test per hook
- FE `CommandPalette` dispatches the correct action per command id
- FE `urlState.ts`: encode({filters, view}) → decode → filters+view round-trip; URL missing a key → default value
- FE i18n: `t('…')` returns ko vs en strings per active locale
- FE `AttackHeatmap`: top-N=30 by default; toggle expands; color scale matches count domain
- FE `WorldMap`: DPRK highlighted regardless of data; tooltip shows country name + count
- FE `TrendChart` / `MotivationDonut` / `YearBar`: render 4 states (loading / empty / error / populated)

### 5.2 Integration (vitest + MSW)

- Filter change → attack_matrix / trend / geo queries all re-fire with new query params, in parallel
- URL deep-link (`/dashboard?date_from=2026-01-01&group_id=1&view=actors&tab=overview`) → FilterStore hydrates from URL on mount → charts fetch with locked params
- Locale switch → chart titles + empty/error copy re-render in new locale
- ⌘K "clear filters" → FilterStore resets → URL updates → charts refetch
- Chart error state does NOT take down sibling charts (per-query error boundary)

### 5.3 Contract (pact-js consumer + live verify)

- PR #13 extends `contracts/pacts/frontend-dprk-cti-api.json` to 8 interactions (5 from PR #12 + 3 new analytics)
- CI `contract-verify` BE job green on all 8
- Provider-state helpers reuse PR #12 fixture shape to keep matcher validity (memory `pitfall_pact_fixture_shape.md`)
- Fixture dates for new interactions fall inside the PR #12 pact filter window `2026-01-01`–`2026-04-18` (memory evidence from PR #12 `06e47e9`)

### 5.4 E2E (Playwright — D9 extension, optional)

- Existing PR #12 journey stays green
- Optional: add URL-state replay assertion — seed cookie → visit `/dashboard?view=actors` → actors tab active without user interaction

### 5.5 Manual verification (reproducible)

- Real dev stack (`docker compose up`) — FE + BE + PG + Redis + Keycloak
- Login as analyst → world map shows DPRK + country aggregates (≥1 country highlighted)
- ATT&CK heatmap renders top-N techniques, toggle expands; tooltip shows technique name + count
- Motivation donut + year bar consistent with KPI strip totals
- Language toggle (if exposed in UserMenu) flips ko ↔ en on all chrome copy
- ⌘K opens palette, all commands execute correctly
- Deep-link URL copy-paste → fresh browser tab reproduces same filters + view
- Lighthouse run (manual) ≥ 90 on all 4 scores (D6 artifact)

---

## 6. Operational

### 6.1 Environment + deploy

- No new FE env vars. `config.ts` unchanged.
- BE: no new env vars for analytics endpoints; they read same DB as `/dashboard/summary`.
- No nginx change. SPA fallback handles URL-state routes.

### 6.2 Database

- No migrations required (analytics endpoints aggregate existing tables).
- **Open:** possible index additions if p95 on `/analytics/attack_matrix` exceeds target. Resolve in Group A implementation based on EXPLAIN ANALYZE output.

### 6.3 Observability

- BE analytics endpoints emit existing request-duration metric (PR #10 middleware).
- FE: no new logging. Chart render errors surface via React error boundary → inline retry card (PR #12 D11 pattern).

### 6.4 CI + status checks

- No new CI jobs.
- Extended jobs: `api-tests` / `api-integration` / `contract-verify` absorb BE analytics; `frontend` / `frontend-e2e` absorb FE viz + i18n + URL-state.
- Lighthouse stays off CI (D6).

### 6.5 Release notes / PR body template

- Mapping to v2.0 §4.2 areas [C] + [D] + [E] + [F]
- D1–D9 lock table (from §2)
- Screenshot pairs: `/dashboard` (light + dark) at 3 states — empty / partial / populated
- Lighthouse artifact (D6) — 4 scores on `/dashboard` in both themes
- i18n demo: screenshot of ko + en side-by-side on one chart with empty state

---

## 7. Risks + mitigations

| Risk | Likelihood | Mitigation |
|:---|:---:|:---|
| `/analytics/attack_matrix` p95 too high under real data | M | EXPLAIN ANALYZE in Group A; add index if needed; cache with React-Query `staleTime` on FE side |
| `@visx` + React 18 concurrent-mode rendering mismatches | L | Known good pairing; `visx` v3 is React 18 compat. Pin version before Group G. |
| TopoJSON bundle size bloats FE | L | Natural Earth 110m world is ~30 KB gzipped. Bundle static; no CDN dependency. |
| i18next SSR / init race on cold load | L | Init `i18next` synchronously before `ReactDOM.render`; load ko + en both upfront (small, not code-split). |
| URL-state encoding causes double-navigation loop | M | `useFilterUrlSync` writes URL via `history.replaceState` on filter change, reads via `useSearchParams` on mount only. Integration test pins no-loop invariant. |
| Lighthouse variance misleads reviewer | M | D6 requires 3-run median, not single run. Dev mode disabled; preview build only. |
| New pact interactions trigger fixture-shape regression | M | Reuse PR #12 Group I helpers (`_ensure_full_group`, `_ensure_incident_with_motivation`); add a Group B integration test per new state (memory `pitfall_pact_fixture_shape.md`) |
| Node 20 GHA deprecation flips during PR | M | 2026-06-02 deadline; if runner images update mid-PR, bump `actions/checkout@v5` etc. in a follow-up commit on this branch |
| OpenAPI snapshot crosses ~200 KB readability threshold | M | Already at ~85 KB; PR #13 adds 3 endpoints + ~6 DTOs. If diff unreadable, path-split OpenAPI snapshot (memory `openapi_snapshot_size_watch.md`) |
| ATT&CK heatmap top-N=30 UX wrong for real analyst workflow | L | N is configurable at render site; can revise default without schema churn. Track feedback for Phase 3. |

---

## 8. Follow-ups queue (post-merge)

New (this PR will surface):

- FE error-report endpoint + FE → OTLP/Loki trace context → Phase 4
- Alerts real-time fetch (WebSocket or SSE) → Phase 4
- Detail views (`/reports/:id`, etc.) → Phase 3
- ⌘K full-text / server-backed search → Phase 3+
- OpenAPI → Zod codegen script (PR #12 D7 defer carries) → tooling PR
- Lighthouse CI gate once variance stabilizes → post-Phase-2
- BE domain-value translation (if analyst feedback requests it) → Phase 3+
- Korea-specific projection secondary chart (if needed) → Phase 3+

Carried (unchanged):

- MITRE TAXII manual smoke (KIDA firewall block)
- Node.js 20 GHA bump (2026-06-02 deadline)
- Worker DQ CLI `SelectorEventLoopPolicy` on Windows
- Staging 30-day auto-purge
- `rejected → pending` admin reopen action
- `review.approval_rate` DQ metric

---

## Lock record

Draft v1 written + Locked 2026-04-18 off `main@1722719`. D1–D9 user-provided candidates adopted verbatim on core positions; six §2.1 open items resolved in one discuss-phase round by extending table detail (see §2.1 revision log). Lock commit lands on `feat/p2.4-dashboard-views` as `docs(plan): lock PR #13 dashboard views plan`.

Plan doc convention: mirrors `docs/plans/pr12-fe-shell.md` per `memory/plan_doc_convention.md`.

# PR #12 — Phase 2.3 FE Shell (Dashboard Layout Skeleton)

**Status:** 🔒 **Locked** — D1–D11 frozen 2026-04-18 after 1-round discuss-phase. Branch creation + Group A execution gated on this doc.

**Branch target:** `feat/p2.3-fe-shell` (to be created at lock commit).

**Base:** `main` at merge commit `0835247` (PR #11 read API + rate-limit + contracts merged).

---

## 1. Goal

Ship the **stable interactive skeleton** for the DPRK CTI dashboard FE — the outer scaffolding that PR #13 (dashboard views: D3 world map, ATT&CK heatmap, Similar Reports, bottom panels) plugs into without re-architecting. "Shell" here covers design doc v2.0 §4.2 areas **[A] top-nav + filters** and **[B] KPI cards** only; areas [C]–[F] are PR #13 scope.

Mapping to v2.0 §14 roadmap: **Phase 2 W1–W2** ("레이아웃, 상단바(필터+TLP+⌘K), KPI 카드, 테마").

Concrete deliverables (frozen):

1. Router + layout shell (Login → Dashboard) with role-gated routes for `/dashboard`, `/reports`, `/incidents`, `/actors` list pages (shell-level only; deep views land in PR #13).
2. Top-nav [A]: title · date-range picker · group filter · TLP filter · 🔔 alerts bell · 👤 user menu · ⌘K trigger.
3. KPI cards [B]: 6-card strip wired to `/api/v1/dashboard/summary` (live, not placeholder — D3).
4. Auth wiring: login redirect → Keycloak → callback → session cookie → FE state seeded from `/api/v1/auth/me`.
5. Theme tokens + working dark/light toggle (D4).
6. Pact consumer contract for 4 interactions (D8) committed to `contracts/pacts/`, flipping PR #11's `contract-verify` job from skip-with-ok → live verify.
7. One Playwright journey — login-seeded shell load → dashboard → actors navigation (D9).

Explicit non-goals (deferred):

- Areas [C] world map, [D] ATT&CK/donut/bar, [E] trend/groups/feed/similar, [F] alerts drawer → PR #13
- ⌘K search + action surface (PR #12 ships trigger + shortcut only) → PR #13
- Detail views (`/reports/:id`, `/incidents/:id`, `/actors/:id`) → Phase 3 (BE D9 lock in PR #11)
- OpenAPI → Zod **codegen script** (D7 defer — PR #13 or later)
- i18n (ko/en) → Phase 2 W6
- a11y audit → Phase 2 W6
- URL-state sync for filters → Phase 2 W6
- Alerts real-time fetch → Phase 4

---

## 2. Decisions Locked (D1–D11)

Locked 2026-04-18 after 1-round user review. Recommended positions from Draft v1 accepted with **three modifications** (D7, D8, D9 — scope shrink) and **two additions** (D10, D11).

| ID | Item | Locked Position | Rationale |
|:---:|:---|:---|:---|
| **D1** | Routing scope | `/login`, `/dashboard`, `/reports`, `/incidents`, `/actors` (list — minimal table + pagination). Detail views out of scope. | Exercises all 4 PR #11 read endpoints + rate-limit 60/min + `/auth/me` in one PR; Pact consumer covers the live surface; PR #13 scope stays on visualizations. |
| **D2** | Auth wiring | On app boot + after login, fetch `/api/v1/auth/me` → seed zustand `useAuthStore` with `CurrentUser` DTO. React-Query cache key `["me"]`, `staleTime: Infinity` until logout mutation invalidates. All API calls use `credentials: "include"`. Route gate: query 401 → redirect to `/login`. **A.1** logout = `POST /api/v1/auth/logout` → clear cookie server-side + invalidate `["me"]` → redirect `/login`. **A.2** 401-loop guard: single forced re-login on session expiry; immediate-post-login 401 treated as config error (no loop). **A.3** CSRF: rely on backend `sameSite=lax` cookie. Explicit CSRF header deferred. | Matches existing `window.__APP_CONFIG__` runtime pattern but sources identity from real API call so role-gating stays authoritative. |
| **D3** | KPI card data | Live via react-query `useQuery(["dashboard", "summary", filters])` hitting `/dashboard/summary`. Loading skeleton + empty + error + populated states. Group filter + date range from top-nav wired. | FE without live data exercise barely validates the BE contracts shipped in PR #11. Placeholder path adds nothing. |
| **D4** | Theme scope | Tokens (colors / typography / spacing / radius / shadow) in `tailwind.config.ts` + `:root` CSS vars + **working dark/light/system toggle**. `useThemeStore` persists `"light" \| "dark" \| "system"` in localStorage; "system" matches `prefers-color-scheme`. Switched via `html[data-theme]`. | Design doc §8.2 lists theme toggle inside Command Palette; shipping tokens + toggle together avoids long-running TBD. |
| **D5** | Top-nav control interactivity | **Date range picker**: working (feeds KPI query). **Group filter**: working (feeds `group_id[]`). **TLP filter**: UI + state only, NO BE filter wired (PR #11 D4 deferred TLP RLS). **Alerts bell** 🔔: static icon + `0` badge, no click handler. **User menu** 👤: working (role badge + logout + theme toggle). **Command Palette ⌘K**: trigger button + `mod+k` shortcut + empty dialog skeleton. | Fully-interactive controls must be backed by a shipped BE contract; TLP + alerts intentionally stubbed to match BE state; ⌘K dialog content is PR #13. |
| **D6** | Router library | `react-router-dom@6` pinned. Nested routes + role-gate HOC pattern. | Mature, zero learning curve, integrates cleanly with react-query. v7 rename + tanstack-router migration deferred. |
| **D7** | API client + schema strategy | **Revised from Draft v1.** Thin hand-written `apiClient` in `src/lib/api.ts` (`fetch` wrapper, `credentials: "include"`, `ApiError` class for 4xx/5xx normalization) + **minimal hand-written Zod runtime schemas** for the four endpoints the shell actively consumes (`/auth/me`, `/dashboard/summary`, `/actors`, `POST /auth/logout`). **OpenAPI→Zod codegen script is deferred to PR #13 or later.** `/reports` + `/incidents` shell list routes use lighter types-only (no runtime validation) for PR #12. | User lock: PR #12 core is screen/routing/auth; schema codegen is tooling PR scope. Hand-written for 4 endpoints is low-maintenance for one cycle; codegen added when example volume justifies it (PR #13 introduces detail panels + expanded DTO surface). |
| **D8** | Pact consumer interactions | **Revised from Draft v1.** Four interactions only: `GET /api/v1/auth/me` (happy + 401), `GET /api/v1/dashboard/summary` (happy with filters), `GET /api/v1/actors` (happy + pagination), `POST /api/v1/auth/logout` (204). **`/reports` + `/incidents` deferred** — Pact coverage lands in PR #13 when detail views + list filters are exercised. | Four covers the shell's load-bearing contracts (identity, KPI, first list route, session teardown); six would turn PR #12 into a list-contract PR by stealth. Plan D7 on the BE (PR #11) already locked verify harness to accept any N — expanding later is additive. |
| **D9** | Playwright E2E scope | **Revised from Draft v1.** ONE journey: login-seeded shell load (forged-cookie pattern, memory `pattern_forged_cookie_verification.md`) → `/dashboard` route loads → KPI strip renders non-loading → navigate to `/actors` → actors table renders first page. Logout flow covered by Vitest integration, not E2E. | Original "login → dashboard → logout" added a multi-redirect assertion for a feature already pinned by unit tests; the navigation smoke is the one invariant PR #12 cannot prove any other way. |
| **D10** | State management split | **New lock.** Zustand for **auth/UI** state only (`useAuthStore`, `useThemeStore`, `useFilterStore`). React-Query for **ALL server state** (`useQuery` / `useMutation` for everything that originates from the BE). No overlap — do NOT mirror server data into zustand stores. Logout mutation invalidates `["me"]`; BE state changes propagate through query cache invalidation, not store setters. | Prevents the classic React pitfall where UI state and server state share a store and drift. Split keeps the source-of-truth boundary explicit for anyone onboarding later. |
| **D11** | Layout loading + error policy | **New lock.** Route-level Suspense boundary + error boundary. Loading = inline skeleton (KPI card shimmer, table row shimmer, nav shell intact). Error = inline retry card within the route ("Reload KPI data" / "Reload actors list"), NOT a global blocking spinner and NOT a full-screen error page. Only unrecoverable auth errors (401 on session expiry) trigger a full redirect. Route transitions use `useNavigation` pending state, not a page-level overlay. | Global blocking spinners hide partial progress and make mid-render errors look like hangs; inline skeleton + inline retry keeps the nav usable and makes recovery a one-click operation. |

### 2.1 Revision log

- D7 (codegen defer), D8 (6→4 pact interactions), D9 (Playwright scope), D10 (new), D11 (new) — all adjusted per user lock 2026-04-18.
- D1–D6 recommended positions adopted verbatim.

---

## 3. Scope

### In scope (new files / major edits)

**Routing + layout:**
- `apps/frontend/src/App.tsx` — replaced with router root + auth bootstrap
- `apps/frontend/src/routes/` — `login.tsx`, `dashboard.tsx`, `reports.tsx`, `incidents.tsx`, `actors.tsx` (all shell-level)
- `apps/frontend/src/layout/Shell.tsx` — outer frame: top-nav + main outlet
- `apps/frontend/src/layout/TopNav.tsx`, `FilterBar.tsx`, `UserMenu.tsx`, `CommandPaletteButton.tsx`
- `apps/frontend/src/layout/RouteGate.tsx` — role-gated route wrapper
- `apps/frontend/src/layout/RouteErrorBoundary.tsx`, `RouteSkeleton.tsx` — D11 loading + error policy

**State + API (D7 hand-written):**
- `apps/frontend/src/stores/auth.ts` — `useAuthStore` (zustand, UI state; D10)
- `apps/frontend/src/stores/theme.ts` — `useThemeStore` (zustand + localStorage)
- `apps/frontend/src/stores/filters.ts` — `useFilterStore` (date range, groups, TLP)
- `apps/frontend/src/lib/api.ts` — thin `apiClient` wrapper + `ApiError` class
- `apps/frontend/src/lib/api/schemas.ts` — hand-written Zod schemas for the D8 four endpoints + `CurrentUser` + `DashboardSummary` + `ActorListResponse`. Types-only interfaces for `ReportListResponse` / `IncidentListResponse` (D7).
- `apps/frontend/src/lib/api/endpoints.ts` — `getMe()`, `getDashboardSummary()`, `listActors()`, `listReports()`, `listIncidents()`, `logout()`
- `apps/frontend/src/lib/queryKeys.ts` — React-Query key factory

**Server-state hooks (D10 react-query only):**
- `apps/frontend/src/features/auth/useMe.ts`, `useLogout.ts`
- `apps/frontend/src/features/dashboard/useDashboardSummary.ts`
- `apps/frontend/src/features/actors/useActorsList.ts`
- `apps/frontend/src/features/reports/useReportsList.ts`
- `apps/frontend/src/features/incidents/useIncidentsList.ts`

**KPI cards:**
- `apps/frontend/src/features/dashboard/KPIStrip.tsx`
- `apps/frontend/src/features/dashboard/KPICard.tsx`

**Theme:**
- `apps/frontend/tailwind.config.ts` — token extensions
- `apps/frontend/src/styles/tokens.css` — `:root` + `[data-theme="dark"]` CSS vars
- `apps/frontend/src/components/ThemeToggle.tsx`
- `apps/frontend/index.html` — inline FOUC-prevention script sets `data-theme` before React hydrates

**Contract + tests:**
- `contracts/pacts/frontend-dprk-cti-api.json` — generated by pact-js consumer tests (D8 four interactions)
- `apps/frontend/src/**/__tests__/*.test.ts` — vitest specs
- `apps/frontend/tests/integration/*.test.ts` — MSW-backed integration
- `apps/frontend/tests/contract/*.pact.test.ts` — pact-js consumer
- `apps/frontend/tests/e2e/login-dashboard-actors.spec.ts` — Playwright single-journey (D9)
- `apps/frontend/playwright.config.ts`
- `apps/frontend/vitest.config.ts` (+ optional separate project config for pact)

**CI:**
- `.github/workflows/ci.yml` — extend `frontend` job to run `pnpm test` + `pnpm test:contract`. Add `frontend-e2e` job (Playwright, artifact upload for videos/traces).
- `contract-verify` BE job (existing) — switch from skip-with-ok to live verify: spin up uvicorn subprocess + set `PACT_PROVIDER_BASE_URL=http://127.0.0.1:<port>` before `pytest tests/contract`. This retires the fail-loud regression guard's trigger condition and makes the test-missing-provider-url case revert to its production posture (present pact + no URL = red).

**Deps (pnpm add — frozen list):**
- `react-router-dom@^6`
- `zod` (runtime schema validation)
- `cmdk` (⌘K dialog skeleton)
- `date-fns` (date-range picker)
- Dev: `@pact-foundation/pact@^13`, `@playwright/test`, `playwright`, `vitest`, `@vitest/ui`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `msw`, `jsdom`
- `@tanstack/react-query` (already present)
- `@tanstack/react-query-devtools` (dev, already provisional)

### Out of scope (explicit)

- Areas [C]–[F] dashboard visualizations → PR #13
- ⌘K search + action surface → PR #13
- Detail routes (`/reports/:id`, etc.) → Phase 3
- **OpenAPI → Zod codegen script** (D7 defer) → PR #13 or later tooling PR
- i18n (ko/en) → Phase 2 W6
- a11y audit → Phase 2 W6
- URL-state sync for filters → Phase 2 W6
- Alerts real-time fetch + drawer → Phase 4
- Pact coverage for `/reports` + `/incidents` (D8 defer) → PR #13
- Logout E2E journey (D9 defer to Vitest integration)
- Service worker / offline mode → not planned in v2.0

---

## 4. Execution order (Groups)

Post-D-lock dependency chain. Nine groups; each = one commit on `feat/p2.3-fe-shell` with green tests before the next starts.

1. **Group A — API client + auth store + `/me` wire.** `src/lib/api.ts` + `ApiError`, Zod schema for `CurrentUser`, `useAuthStore`, `useMe`, `useLogout` hooks. Unit tests: apiClient error normalization, store transitions, 401-loop guard (D2.A.2).
2. **Group B — Router + Shell layout skeleton.** `react-router-dom@6`, `<RouterProvider>`, `Shell`, `TopNav` structural, `RouteGate` role gate, `RouteErrorBoundary` + `RouteSkeleton` (D11 policy), login route.
3. **Group C — Theme tokens + dark/light toggle.** Tailwind config extensions, `tokens.css`, `useThemeStore`, `ThemeToggle`, FOUC-prevention inline script.
4. **Group D — Filter bar stores + UI.** `useFilterStore`, `FilterBar` with date range + group filter (working) + TLP (UI-only, D5 lock).
5. **Group E — KPI cards live-wired.** Zod schema for `DashboardSummary`, `useDashboardSummary` hook, `KPIStrip` + `KPICard` with 4 render states (loading / empty / error / populated). Depends on A + D.
6. **Group F — List route placeholders with live data.** Zod for `ActorListResponse`; types-only for `ReportListResponse` / `IncidentListResponse` (D7). Minimal table + pagination + skeleton/error. `/reports` + `/incidents` call the endpoints but stay shell-level (no filter surface beyond what the FilterBar provides).
7. **Group G — User menu + logout + ⌘K trigger.** `UserMenu` (role badge + logout + theme toggle + keyboard shortcut hint), `CommandPaletteButton` with `mod+k` listener + empty `cmdk` dialog skeleton.
8. **Group H — Pact consumer tests.** Four interactions (D8): `/auth/me` (happy + 401), `/dashboard/summary` (happy with filters), `/actors` (happy + pagination), `POST /auth/logout` (204). Emits `contracts/pacts/frontend-dprk-cti-api.json`.
9. **Group I — CI wiring + Playwright E2E.** Extend `frontend` job for vitest + pact tests. Add `frontend-e2e` job. Switch `contract-verify` BE job from skip-with-ok to live verify (uvicorn subprocess + `PACT_PROVIDER_BASE_URL`). One Playwright journey (D9): login-seeded → `/dashboard` KPI render → navigate `/actors`.

Parallelization after the lock commit: A is sequential-first. C, D can run parallel with B. E waits for A + D. F waits for B + A. G after B + C. H after E + F (pact tests need real stores + endpoints wired). I is last.

---

## 5. Acceptance tests

### 5.1 Unit (vitest + RTL)

- `apiClient.fetch()` throws typed `ApiError` on 4xx/5xx with normalized `status` / `detail`; 2xx returns parsed Zod schema output
- `useAuthStore` transitions: unauth → auth (on `/me` success), auth → unauth (on logout mutation success + on 401 during any authenticated query)
- 401-loop guard (D2.A.2): synthetic 401 immediately after login does NOT re-trigger the login redirect
- `useThemeStore` persists + reads from localStorage; "system" mode reacts to `prefers-color-scheme` media query
- `useFilterStore` composes query-param payload correctly for `useDashboardSummary`
- `KPICard` renders 4 states (loading / empty / error / populated) from fixtures
- Zod schemas parse the `contracts/openapi/openapi.json` example payloads without error (pinned against BE snapshot drift)
- React-Query key factory stability (key changes on filter change, stable when filter unchanged)

### 5.2 Integration (vitest + MSW)

- Bootstrap: mocked `/me` → `useAuthStore.authenticated = true` → dashboard renders
- Logout mutation: invalidates `["me"]` cache → auth store unauth → redirect `/login` (D2.A.1)
- 401 mid-session on `/dashboard/summary` → redirect `/login` (D2.A.2, single re-login)
- Filter change → KPI query re-fires with new query params
- TLP checkbox state persists in zustand but does NOT appear in any outgoing request (D5)

### 5.3 Contract (pact-js consumer)

- D8 four interactions produce one `frontend-dprk-cti-api.json` file
- CI `contract-verify` BE job verifies against live uvicorn — all 4 interactions green
- Deferred `/reports` / `/incidents` interactions explicitly noted in a README in `apps/frontend/tests/contract/` so PR #13 author knows the gap

### 5.4 E2E (Playwright — D9 single journey)

1. Seed signed session cookie via the forged-cookie helper (skip Keycloak redirect; see memory `pattern_forged_cookie_verification.md`)
2. Visit `/dashboard` → KPI strip renders 6 cards in populated state
3. Click sidebar / nav link to `/actors` → actors table renders first page with at least one row
4. Artifacts uploaded on failure: screenshot + video + trace

### 5.5 Manual verification (reproducible)

- Real dev stack (`docker compose up`) — FE `localhost:5173`, BE `localhost:8000`, Keycloak `localhost:8081`
- Login as `analyst` / `researcher` / `policy` / `soc` — user menu shows correct role badge
- Theme toggle flips light/dark + persists across refresh; "system" mode respects OS preference
- Rate limit: hold refresh 60+ times on dashboard → KPI query 429 surfaces as inline error card, not a crash

---

## 6. Operational

### 6.1 Environment + deploy

- No new BE env vars. FE `config.ts` unchanged (`VITE_API_URL` / `VITE_APP_ENV` + runtime `window.__APP_CONFIG__`).
- nginx container: no config change. Existing SPA fallback for unknown routes already in `nginx.conf` handles react-router client-side routing.

### 6.2 Database

- No migrations. FE only.

### 6.3 Observability

- FE errors → `console.error` in dev only. `src/lib/logger.ts` noop-suppresses in prod (addressing the `rules/typescript/hooks.md` console-log hook). BE error-report endpoint deferred to Phase 4.

### 6.4 CI + status checks

- New required checks:
  - `frontend` (existing job, extended with vitest + pact tests)
  - `frontend-e2e` (new Playwright job)
- Updated check:
  - `contract-verify` — switches from skip-with-ok to live-verify. The fail-loud regression guard in `test_missing_provider_url_with_pacts_present_fails_loudly` continues to pin the "pact present but URL unset = red" contract.
- Unchanged: `api-tests`, `api-integration`, `db-migrations`, `data-quality-tests`, `worker-tests`, `python-services×3`.

### 6.5 Release notes / PR body template

At PR open:

- Mapping to v2.0 §4.2 areas [A] + [B]
- D1–D11 lock table (from §2)
- Screenshot pair: `/login` + `/dashboard` in both light and dark themes
- Partial Lighthouse score on `/dashboard` (M2 target ≥ 90 is Phase 2 exit — PR #12 is mid-milestone, PR #13 takes it to 90+)

---

## 7. Risks + mitigations

| Risk | Likelihood | Mitigation |
|:---|:---:|:---|
| Pact consumer tests interact badly with MSW in Vitest | M | Isolate pact tests in `apps/frontend/tests/contract/` with a separate vitest project config; pact-js manages its own mock server |
| Keycloak dev realm `directAccessGrantsEnabled=false` blocks Playwright login flow | H | D9 explicitly uses forged-cookie pattern (`pattern_forged_cookie_verification.md`); E2E journey skips Keycloak redirect entirely |
| Theme toggle causes FOUC on initial paint | M | Inline `<script>` in `index.html` reads localStorage + sets `html[data-theme]` before React hydrates |
| React-Query cache invalidation on logout leaks across users in dev (multi-tab) | L | `queryClient.clear()` inside logout mutation's `onSuccess`; memoized across tabs via `broadcastChannel` adapter — defer to PR #13 if overkill |
| Zod schema hand-write drift vs BE snapshot | M | Unit test 5.1 "Zod schemas parse the openapi.json example payloads" pins the contract; if BE example updates without a matching FE Zod edit, this test fails. D7 codegen defer acknowledged — this test is the stopgap. |
| `contract-verify` CI job's new uvicorn subprocess boot flaky | M | Use `uvicorn --port 0` → read port from `--log-config` JSON, OR pick a deterministic high port; give it a 10s startup timeout with a `/healthz` poll; fail the job on timeout rather than silently proceeding |
| cmdk + React 18 concurrent features incompatibility | L | Pin known-good version; fallback to a simple `<dialog>` if issues surface (⌘K dialog content is PR #13 anyway) |

---

## 8. Follow-ups queue (post-merge)

New (this PR will surface):

- Phase 2 W3–W6 — D3 map, ATT&CK heatmap, Similar Reports, bottom panels, ⌘K search/action surface, URL-state sync, i18n, a11y audit → PR #13
- OpenAPI → Zod **codegen script** (D7 defer) → PR #13 tooling chunk, or standalone tooling PR
- Pact coverage for `/reports` + `/incidents` (D8 defer) → PR #13 when detail views + advanced filters land
- E2E logout journey (D9 defer to Vitest integration) — optionally promoted to Playwright in PR #13 if the multi-redirect flow gets complex
- Phase 4 — FE error-report endpoint + FE→OTLP/Loki trace context

Carried from PR #11 (unchanged):

- OpenAPI snapshot size watch — path-split if PR #12/13 example growth exceeds ~200 KB diff readability (memory `openapi_snapshot_size_watch.md`)

Carried from PR #10:

- MITRE TAXII manual smoke (KIDA firewall block)
- Node.js 20 GHA bump (2026-06-02 deadline) — **may trigger during PR #12 if `pnpm` CI image bumps**, watch for action-runner incompat
- Worker DQ CLI `SelectorEventLoopPolicy` on Windows
- Staging 30-day auto-purge
- `rejected → pending` admin reopen action
- `review.approval_rate` DQ metric

---

## Lock record

Draft v1 → Locked 2026-04-18. One discuss-phase round. D1–D6 adopted verbatim from Draft v1 recommendations; D7/D8/D9 revised for scope shrink per user review; D10/D11 added.

Plan doc convention: mirrors `docs/plans/pr11-read-api-surface.md` per `memory/plan_doc_convention.md`. Lock commit goes on the `feat/p2.3-fe-shell` branch as `docs(plan): lock PR #12 FE shell plan`.

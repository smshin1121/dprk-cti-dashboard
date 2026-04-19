# PR #14 — Phase 3 slice 1: Detail views + Similar Reports live

**Status:** 🔒 **Locked 2026-04-19** — D1–D11 frozen after 1-round discuss-phase. OI1–OI4 resolved as reviewer-recommended locks (A / A-with-empty-state-fallback / B / A). Execution starts with Group A on branch `feat/p3.1-detail-views`.

**Base:** `main` at `8d66c9f` (PR #13 merge).

**Mapping to design doc v2.0 §14 Phase 3:** this PR covers **W3 F-1** (Similar Reports via `pgvector`) + **W4** (detail drill-down, incident↔report bidirectional linking through the existing `incident_sources` join). The rest of Phase 3 — **W1 A-1/F-2** (attribution graph + probability), **W2 D-1/F-4** (correlation w/ lag + geopolitical), **W3 F-5** (CVE weaponization) — is carried to subsequent Phase 3 slices.

---

## 1. Goal

Close the two Phase 2.4 carry-overs (the `SimilarReports` stub and the `ReportFeed` row click that goes nowhere) by shipping the **detail-view + similar-reports** surface:

1. **BE:** `GET /api/v1/reports/{id}` + `/incidents/{id}` + `/actors/{id}` + `/reports/{id}/similar`.
2. **FE:** 3 detail routes (`/reports/:id`, `/incidents/:id`, `/actors/:id`) with live queries + Zod validation.
3. **FE:** `SimilarReports` panel moves from the Phase 3 stub on the dashboard to the **report detail page** with live pgvector kNN.
4. **FE:** Cross-links — `ReportFeed` row → `/reports/:id`, `GroupsMiniList` row → `/actors/:id`, plus incident↔report links that traverse the existing `incident_sources` FK (no new schema).

### Explicit non-goals (within Phase 3 roadmap, deferred to later slices)

- Attribution probability graph (A-1 / F-2) — separate Phase 3 PR
- Correlation analysis with lag (D-1) — separate PR
- Geopolitical correlation (F-4) — separate PR
- CVE weaponization (F-5) — separate PR
- `/api/v1/search` hybrid full-text + vector — separate PR (⌘K carry; see OI3 / D3)
- Alerts drawer live wiring — Phase 4 (PR #13 lock carries)
- Detail-page charts (per-actor trend, report timeline) — defer until analyst UAT says they're useful
- Fake/heuristic similarity fallback when embeddings are missing — explicitly blocked by **D10**

---

## 2. Decisions — LOCKED 2026-04-19

| ID | Item | Locked | Rationale |
|:---:|:---|:---|:---|
| **D1** | Detail endpoint scope | **3 endpoints: `GET /reports/{id}`, `/incidents/{id}`, `/actors/{id}`.** Shallow joins only (see **D9**) — all fields of the list-item DTO plus a bounded set of related-entity summaries. TLP-aware via authenticated session (RLS deferred per PR #11 D4). **60/min per-user per-route** rate limit (same bucket tier as the list endpoints). | §14 W4 "드릴다운" ask. Read-only GETs, no new aggregator shapes beyond joins over the existing schema. Per-route bucket scoping matches PR #11/13 precedent. |
| **D2** | SimilarReports live wiring | **Include `GET /reports/{id}/similar` (F-1, §5.5) per D8 semantics.** Replaces the PR #13 `SimilarReports` stub — the panel moves from `DashboardPage` to `ReportDetailPage` (its natural home: "similar to what?" needs a selection anchor). **Precondition recorded in R1:** schema has `reports.embedding vector(1536)` (migration 0001) — column existence is confirmed; runtime **backfill readiness** is a separate concern covered by D10's missing-data contract. | `pgvector` column was seeded by migration 0001 but we do NOT assume every seeded report has an embedding populated in every environment. Handling that gap at the contract level (D10) keeps the feature honest without blocking the slice on a backfill campaign. |
| **D3** | ⌘K scope (carry from PR #13) | **Unchanged — local nav + theme + clear filters + sign out.** No server search in this PR. | `/api/v1/search` has its own surface (hybrid ranking, latency budget per §7.7 ≤ 500 ms, Redis cache, auth scope, cross-type result disambiguation). Adding it to the detail-views PR would turn this into a search PR — carry it to a dedicated slice. |
| **D4** | URL-state deep-link contract | **Detail IDs live in the URL PATH (`/reports/:id`, etc.) via React Router, NOT in the query string. Query-string whitelist unchanged from PR #13 (5 keys: `date_from`, `date_to`, `group_id`, `view`, `tab`).** Cross-panel selection (ATT&CK tactic expand, geo country hover-pin, SimilarReports k value) stays ephemeral React state. | PR #13 D4 locked "ephemeral UI stays OUT of URL state" for concrete reasons (hydration races, back-button surprises, the zustand+useLayoutEffect trap — see memory `pitfall_zustand_useSyncExternalStore_layout_effect`). Detail navigation already fits the path-param contract cleanly. No widening in this slice. |
| **D5** | Pact consumer extension | **4 new interactions: `/reports/{id}` happy, `/incidents/{id}` happy, `/actors/{id}` happy, `/reports/{id}/similar` happy with `k=10`.** Matchers follow the PR #13 Group J discipline — `eachLike` for array fields, all non-empty per BE fixture (or explicitly empty where D10 dictates a graceful empty contract). No `group_id` on any of these (detail endpoints don't accept it). Path parameter matchers for `{id}` use V3 path-matching syntax — validated in discuss-phase per memory `pitfall_pact_js_matchers_on_headers` (panic risk is headers-only; body + path have been safe in prior PRs). | Consumer-driven lift of PR #13's 8 → 12 interactions. Detail DTOs graduate from types-only (PR #12 D7 defer) to Zod-validated (contract + FE ingest both pin shape). |
| **D6** | Lighthouse manual run (carry from PR #13 D6) | **Manual, NOT CI hard gate.** Add `/reports/:id`, `/incidents/:id`, `/actors/:id` to the audit target list in `apps/frontend/lighthouse/README.md`. Same harness, same reviewer model. | PR #13 D6 locked the manual artifact pattern; adding detail routes to the target list keeps the M3 exit Lighthouse snapshot complete. |
| **D7** | In-scope navigation contract | **See D11 for the explicit list.** No dead links — every NavLink ships only if the target BE endpoint + FE route both land in this PR. | Avoid the pattern where UI links jump ahead of the contract. Only wire what works end-to-end by merge. |
| **D8** | Similar endpoint semantics | **`GET /reports/{id}/similar?k=10`.** Contract: **(a)** exclude self — the source report is never in results. **(b)** stable sort — `score DESC, report_id ASC` tie-break so the same input produces the same ordering across runs. **(c)** Redis cache key includes both `report_id` AND `k`. **(d)** `k ∈ [1, 50]`, default 10. **(e)** scores returned in the payload (`items: [{report: ReportListItem, score: float}]`). | Stable sort pins Pact expectations; tie-break by `report_id ASC` is the cheapest deterministic order. Cache key on `(report_id, k)` avoids cross-k pollution. Exclude-self is a correctness property — returning the source report with similarity 1.0 would burn a Top-k slot for zero information. |
| **D9** | Detail payload depth | **Shallow joins only.** Heavy related collections are **capped**: report → at most 10 most-recent linked incidents, incident → at most 20 linked reports, actor → at most 10 linked codenames (already bounded) + at most 10 most-recent linked reports. **No recursive nesting** — a report's linked incidents do NOT embed their own source reports; clients navigate to a second detail endpoint for drill-down. Link targets are `{id, title/summary, published/reported}` summaries, not full list-item DTOs. | First detail slice — payload-explosion risk is real. Caps are conservative; raising them after UAT is cheap. No recursion eliminates the payload-size blowup path where a report with 5 linked incidents each with 20 linked reports produces a 100-item fan-out in a single response. |
| **D10** | Missing similarity data behavior | **Source report exists but has no embedding → `200 OK` with `{items: []}`.** Same for "embedding exists but kNN returns zero results" after the exclude-self filter. **`500` is forbidden** for this class. **No fake / heuristic fallback** (no "return most recent 10 reports" stand-in, no "similar by shared tag" best-effort). If real similarity can't be computed, the contract says empty. | Backfill readiness is environment-dependent; `200 + []` is the honest signal an analyst needs ("no data yet") vs a spurious ranking masquerading as semantic similarity. Explicit empty contract is also easier to pact: one matcher shape, two valid bodies (populated and empty). |
| **D11** | Navigation contract (binds D7) | **In-scope navigations, all verified against schema:** `ReportFeed` row → `/reports/:id` (row has `report.id` already); `GroupsMiniList` row → `/actors/:id` (top-groups payload carries `group_id`); `ReportDetailPage` → lists linked incidents via `incident_sources` join (FK `incident_sources.report_id → reports.id`) → each row → `/incidents/:id`; `IncidentDetailPage` → lists linked reports via the same `incident_sources` join → each row → `/reports/:id`. **Out of scope until a BE contract ships:** AttackHeatmap cell → "incidents/reports by technique" (no endpoint), WorldMap country → "incidents by country" (no endpoint), AlertsDrawer row (Phase 4), ActorDetail → "reports that mention this actor" (would need a `report_codenames`-joined endpoint — candidate for a later Phase 3 slice). | `incident_sources (incident_id PK, report_id PK)` in migration 0001 is the canonical link. incident ↔ report is bidirectional through this M:N join. Everything else is still speculative and would be a forced UI link without a contract. |

### 2.1 Open Items — RESOLVED (1-round discuss-phase 2026-04-19)

- **OI1 → A (Combined single PR).** Detail views + SimilarReports land in one PR #14. Rationale: the 4 BE endpoints and 3 FE routes are tightly coupled; split adds a BE/FE drift window without offsetting gain. Total surface is still smaller than PR #12+#13 combined.
- **OI2 → A (Include live SimilarReports) with empty-state fallback.** Live pgvector kNN ships. Codified in **D10**: when embeddings are absent or kNN returns zero, respond `200 + {items: []}`. Fake / heuristic fallback (e.g., "most recent N reports", "shared-tag overlap") is explicitly prohibited.
- **OI3 → B (⌘K stays local).** Server search deferred to its own PR. ⌘K scope from PR #13 D3 carries forward unchanged.
- **OI4 → A (5-key whitelist + path).** URL-state D4 from PR #13 stays verbatim. Detail navigation uses React Router path params; cross-panel selection stays ephemeral.

---

## 3. Scope

### In scope — BE

- `services/api/src/api/routers/detail.py` *(NEW)* — 3 detail routes (or per-entity file; finalized in Group A)
- `services/api/src/api/routers/similar.py` *(NEW)* — `/reports/{id}/similar`
- `services/api/src/api/read/detail_aggregator.py` *(NEW)* — joins for all 3 entity details; cap-enforcement per **D9**
- `services/api/src/api/read/similar_service.py` *(NEW)* — pgvector kNN + Redis cache + **D8** stable sort + **D10** empty contract
- `services/api/src/api/schemas/read.py` — +4 DTOs: `ReportDetail`, `IncidentDetail`, `ActorDetail`, `SimilarReportsResponse`
- `services/api/src/api/routers/pact_states.py` — +4 `.given(...)` handlers; at least one state seeds a report WITH populated embedding + known-cosine-similarity neighbors so **D8** sort + **D10** populated-case are both exercised
- `services/api/tests/unit/` — per-endpoint unit tests, including **D8 stable-sort regression guard** and **D10 empty-contract guards** (no embedding, zero-result kNN)
- `services/api/tests/integration/` — real-PG tests (skip without `POSTGRES_TEST_URL`)
- `contracts/openapi/openapi.json` — regenerated (27 → 31 paths)

### In scope — FE

- `apps/frontend/src/routes/ReportDetailPage.tsx` + `IncidentDetailPage.tsx` + `ActorDetailPage.tsx`
- `apps/frontend/src/routes/router.tsx` — +3 path-param routes
- `apps/frontend/src/features/detail/useReportDetail.ts` / `useIncidentDetail.ts` / `useActorDetail.ts`
- `apps/frontend/src/features/similar/useSimilarReports.ts`
- `apps/frontend/src/features/similar/SimilarReportsPanel.tsx` — live panel, 4 render states
- `apps/frontend/src/features/dashboard/SimilarReports.tsx` — **DELETED** (stub retired; old Phase 3 placeholder on the dashboard disappears)
- `apps/frontend/src/routes/DashboardPage.tsx` — remove the stub mount
- `apps/frontend/src/lib/api/schemas.ts` — +4 Zod schemas (`ReportDetail`, `IncidentDetail`, `ActorDetail`, `SimilarReportsResponse`); PR #12 D7 types-only → Zod upgrade for the detail shapes
- `apps/frontend/src/lib/api/endpoints.ts` — +4 endpoint helpers
- `ReportFeed` row → NavLink to `/reports/:id` (per **D11**)
- `GroupsMiniList` row → NavLink to `/actors/:id` (per **D11**)
- `apps/frontend/tests/contract/frontend-dprk-cti-api.pact.test.ts` — +4 interactions (8 → 12)
- `apps/frontend/tests/e2e/` — +1 optional journey: click ReportFeed row → `/reports/:id` loads → SimilarReports panel renders (empty or populated per fixture; **both valid per D10**)

### Out of scope

- Attribution graph / correlation / CVE / geopolitical (other Phase 3 slices)
- `/api/v1/search` hybrid (its own PR)
- Alerts drawer live wiring (Phase 4)
- Detail-page charts (per-actor trend, report timeline) — gated on UAT
- `technique_id` / `iso2` / `selected_report` in URL query (OI4 answer = A)
- Bulk delete / edit on detail pages
- ActorDetail → "reports that mention this actor" view (would need a `report_codenames`-joined endpoint — candidate for later Phase 3 slice)
- Embedding backfill / re-embedding worker flow (pre-existing or next-milestone responsibility; this PR only consumes what's present)

---

## 4. Execution order (Groups)

1. **Group A — BE detail endpoints** (D1, D9, D11). 3 routes + aggregator + DTOs with capped related collections + unit + integration + OpenAPI regen. No FE touch.
2. **Group B — BE `/reports/{id}/similar`** (D2, D8, D10). pgvector query + stable sort + Redis cache + empty-embedding contract. Unit + integration. Depends on A (uses `ReportListItem` DTO shape in the response row type).
3. **Group C — BE pact provider-state handlers** (D5). 4 new `.given(...)`. At minimum: one state with populated embedding + similarity neighbors; one "no embedding" state to exercise D10 empty contract.
4. **Group D — FE client layer**. 4 Zod schemas + 4 endpoints + 4 React Query hooks. Depends on A + B.
5. **Group E — FE detail pages** (D1, D11). 3 routes + router wiring + cross-links from `ReportFeed` / `GroupsMiniList`. Incident ↔ report linked rows within detail pages use `incident_sources`-derived summaries per D11.
6. **Group F — FE SimilarReports live** (D2, D10). `SimilarReportsPanel` replaces the PR #13 stub. Panel mounts on `ReportDetailPage`. `DashboardPage` loses the stub mount; `features/dashboard/SimilarReports.tsx` deleted.
7. **Group G — FE pact consumer extension** (D5). +4 interactions; pact JSON regenerated (8 → 12). Deliberately no `group_id` (Codex R1 P2 discipline carried). At least the similar interaction uses the populated-embedding fixture; a second (optional) similar interaction against the empty-embedding state pins D10.
8. **Group H — Lighthouse manual re-run** (D6). Reviewer adds the 3 detail routes to the target list and attaches the refreshed SUMMARY.md to the PR body.

**Parallelism:** A → B sequential (similar response embeds a ReportListItem-shaped summary). C parallel with B. D after A+B. E/F wait for D. G after C+F. H last.

---

## 5. Acceptance tests

### 5.1 Unit (pytest / vitest)

- BE detail endpoints return `404` on unknown ID (per-entity) + `422` on non-integer ID.
- BE `/reports/{id}/similar` k-bound: `k<1` → 422; `k>50` → 422; default=10 when omitted.
- **BE D8 stable-sort regression guard:** two result rows with identical scores → ordered by `report_id ASC`; exclude-self invariant pinned.
- **BE D10 empty-contract guards:** (a) source report has `embedding IS NULL` → `200 + {items: []}`. (b) kNN returns zero rows (e.g., only the source report has an embedding) → `200 + {items: []}`. (c) No 500 on either path.
- **BE D9 cap guards:** detail payloads bounded — linked collections never exceed the documented cap; test injects > cap rows and asserts the response is truncated at the limit with the newest-first ordering.
- FE Zod schemas parse OpenAPI example payloads for all 4 new shapes.
- FE hooks subscribe to path-param `id` only — `useDashboardSummary` filter changes do NOT refetch detail hooks.
- FE `SimilarReportsPanel` covers 4 render states (loading / error / empty / populated). **D10-specific test:** empty state renders a documented "No similar reports yet" message, NOT a loading spinner and NOT an error card.

### 5.2 Integration (real-PG)

- Cross-linking: seed incident with 2 report rows in `incident_sources`; fetch `/incidents/{id}` shows both capped summaries; fetch one of the reports, `/reports/{id}` lists the incident in the linked-incidents collection. Bidirectional M:N traversal pinned by both directions.
- Similar kNN: seed 3 reports with hand-crafted embeddings where cosine distances are known; assert `score DESC, report_id ASC` across a tie.
- D10 empty contract: seed a report with NULL embedding; assert live endpoint returns `200 + {items: []}`.

### 5.3 Contract (Pact)

- 4 new consumer interactions, matchers aligned with BE fixture output.
- Provider-state handlers seed non-empty fixtures per interaction (and one empty-embedding state for D10 optional coverage).

### 5.4 E2E (Playwright, optional)

- Seeded session → `/dashboard` → click `ReportFeed` row → `/reports/:id` loads → `SimilarReportsPanel` renders. Accept both populated and empty states per D10 (test asserts panel testid is present, not that it has rows).

---

## 6. Risks

- **R1 — Embedding backfill readiness ≠ column existence.** `reports.embedding vector(1536)` column has existed since migration 0001 (confirmed), but we do NOT assume every seeded report has an embedding populated in every environment. `bootstrap_sample` / worker-populated datasets may or may not carry embeddings. **Mitigation:** D10 codifies the graceful-empty contract at the BE edge so missing data never produces a 500 or a red Pact. **Verify in Group B:** real-PG integration test seeds a report with NULL embedding and asserts `200 + {items: []}`. **Verify in Group C:** at least one `.given(...)` state explicitly seeds populated embeddings so the populated pact interaction has real rows to verify against; a second optional state covers the NULL-embedding empty case.
- **R2 — Detail DTO shape creep.** Keeping shallow joins per D9 vs adding "recently linked incidents with their own linked sources" sub-pagination is a scope-creep risk. **Mitigation:** D9 cap table (10 incidents per report, 20 reports per incident, 10 codenames per actor) is the binding scope contract; adding per-sub-collection pagination is an explicit future-PR ask, not in this PR's surface.
- **R3 — Pact path-parameter matchers.** `pact-js` V3's path matcher syntax for `{id}` needs a sanity check — memory `pitfall_pact_js_matchers_on_headers` warns of panic-prone matcher placement (panic is headers-only in past occurrence, but path-param matchers haven't been exercised in this project yet). **Mitigation:** Group G starts with a minimal path-matcher smoke test before wiring all 4 interactions; fallback is to hardcode the ID (e.g., `/api/v1/reports/42`) in the request path and rely on state-handler seeding of id=42.
- **R4 — `incident_sources` traversal performance.** Report detail's "linked incidents" collection does a join through `incident_sources`; D9 caps it at 10, but the cost is still an indexed join per detail request. **Mitigation:** assert the `incident_sources` table has an index on `report_id` in Group A; if absent, add the index as part of Group A. Migration 0001 creates the table with both columns in the PK, which gives an implicit index on `(incident_id, report_id)` but not on `report_id` alone — worth verifying.

---

## 7. References

- **Design doc v2.0:** §5.5 Similar Reports, §7.6 API endpoint list, §7.7 performance strategy (pgvector cache ≤ 500 ms p95), §14 Phase 3 roadmap
- **PR #13 carry-overs closed by this PR:** `SimilarReports` stub (retired per D2 + D10), `ReportFeed` row click (now navigates per D11)
- **PR #11:** 60/min per-route rate-limit pattern, OpenAPI 3.1 examples discipline
- **PR #12 D7:** types-only for /reports + /incidents list DTOs — this PR graduates the DETAIL shapes (not list) to Zod; list shapes stay as-is
- **Migrations referenced:** `0001_initial_schema.py` (creates `reports.embedding`, `incident_sources`, all FKs); no new migration expected from this PR unless R4 surfaces a missing `report_id` index
- **Memories:**
  - `pitfall_pact_fixture_shape` — all pact fixtures non-empty + non-null + dates inside window; D10's empty contract is the deliberate exception
  - `pitfall_pact_js_matchers_on_headers` — headers only; path-param matchers untested here, Group G smoke
  - `pattern_shared_query_cache_multi_subscriber` — not currently used by detail hooks (each detail ID is a distinct cache key); revisit if a future viz shares a detail query
  - `feedback_real_build_check` — `pnpm run build` authoritative, not `tsc --noEmit`
  - `pitfall_i18next_v26_init_options` — no regression expected; detail pages add new `detail.*` translation keys in `ko.json` + `en.json`

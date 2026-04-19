# PR #15 — Phase 3 slice 2: ActorDetail → linked reports

**Status:** 🔒 **Locked 2026-04-19** — D1–D18 frozen after 1-round discuss-phase. OI1–OI6 resolved as A/A/A/A/A/A. D9 response shape corrected against actual `ReportListResponse` codec. Query lives in a dedicated `api.read.actor_reports` module (not `detail_aggregator.py`) per reviewer separation-of-concerns note. Execution starts with Group A on branch `feat/p3.2-actor-reports` (off `e73319d`).

**Base:** `main` at `e73319d` (PR #14 merge).

**Mapping to design doc v2.0 §14 Phase 3:** this PR covers the ActorDetail → reports-mentioning-this-actor surface that was **explicitly carried out of PR #14** under D11 ("deliberately does NOT traverse `report_codenames`"). No new schema — `report_codenames (report_id PK, codename_id PK, confidence nullable)` already exists from migration 0001 with index `ix_report_codenames_codename_id` from migration 0002:165. Other Phase 3 slices (A-1 attribution graph, D-1 correlation, F-4 geopolitical, F-5 CVE, `/search` hybrid) remain carried.

---

## 1. Goal

Close the PR #14 D11 carry-over by shipping the **actor → reports** surface:

1. **BE:** `GET /api/v1/actors/{id}/reports` — list-shaped, keyset-paginated, date-filterable, reusing the `/reports` list DTO + pagination helper so the FE can reuse render components.
2. **FE:** new "Linked Reports" panel on `ActorDetailPage`, living below the codenames section, with the same 4-state render contract as `SimilarReportsPanel` (loading / error / D10-style empty / populated).
3. **FE cross-links:** each row in the new panel links to `/reports/:id` (existing detail page, no BE churn).
4. **Contract:** +1 OpenAPI path (30 → 31), +2 pact interactions (populated + empty), +1-2 new provider-state handlers on pinned-id actors.
5. **D11 continuity:** the existing `ActorDetail` DTO shape, `actorDetailSchema` strip-mode invariant, and "no reports-like key on ActorDetail" regression guards ALL stay green. Reports come from a **sibling endpoint**, not from enriching the detail shape.

### Explicit non-goals (within Phase 3 roadmap, deferred to later slices)

- Full `/reports` filter subset on `/actors/{id}/reports` (q / tag / source / TLP) — date + cursor only this slice (see D2)
- `report_codenames.confidence` surfaced as attribution signal — follow-up once ETL confidence-population is reviewed (see D11)
- Attribution graph / correlation / CVE / geopolitical / `/search` hybrid — their own Phase 3 slices
- ActorDetail charts (per-actor trend, technique distribution) — gated on analyst UAT
- Reverse navigation: report → "actors mentioned in this report" panel — `report.codenames[]` already carries alias strings; adding group linking is its own slice
- Editing / tagging of the link (e.g., flagging a false-attribution report) — out-of-scope, needs mutation policy review

---

## 2. Decisions — DRAFT (awaiting 1-round discuss-phase)

| ID | Item | Proposed lock | Rationale |
|:---:|:---|:---|:---|
| **D1** | Endpoint shape | **`GET /api/v1/actors/{id}/reports?date_from=&date_to=&cursor=&limit=`** — nested resource path, not a `/reports?actor_id=N` filter extension. | REST semantics ("reports of this actor"); independent rate-limit bucket per slowapi per-route; keeps `/reports` filter surface locked under PR #11 D5 without widening it. PR #14 D11 already used "dedicated endpoint" wording for the carry. |
| **D2** | Filter surface | **Minimal: `date_from` + `date_to` + `cursor` + `limit` only.** No `q` / `tag` / `source` / `tlp` filter on this slice. | First cut; keeps slice small; filter layering can be added in a follow-up if analyst UAT asks. Cross-cutting by tag/q is secondary to the primary ask ("which reports mention this actor?"). `tlp` gating is session-scoped already (PR #11 D4 — RLS deferred), not a filter param. |
| **D3** | Pagination | **Keyset `(published, id)` reusing `api.read.pagination` helper from PR #11** — same cursor codec as `/reports`. | Cursor-stability tests at PR #11 Group K already pin the shape; reuse means zero new cursor semantics to validate. Offset would duplicate `/reports` behaviour inconsistently. |
| **D4** | Default sort | **`reports.published DESC, reports.id DESC`** — newest first, id tiebreak. | Mirrors `/reports` list (PR #11 Group C). |
| **D5** | Dedup when a report links to actor via multiple codenames | **DISTINCT on `reports.id`** — EXISTS subquery or DISTINCT ON (PG) / distinct-subquery (sqlite). A report linked via 3 codenames appears once. | Analyst UX: duplicates are noise. PR #11 Group C already used EXISTS dedup for the tag/source AND/OR filter — same pattern. |
| **D6** | Rate limit | **60/min per-user per-route** via `_limiter.limit("60/minute")` + `session_or_ip_key`. Bucket is independent of `/actors/{id}` detail endpoint and `/reports` list. | Slowapi per-route scoping precedent from PR #11 Group H; nothing new. |
| **D7** | RBAC | **`analyst / researcher / policy / soc / admin`** — same 5 read roles as the list surface. | Inherited lock. |
| **D8** | Empty contract | **Actor exists but has no codenames, OR codenames exist but no linked reports, OR date filter excludes everything → `200` + `{items: [], next_cursor: null, total: 0}`.** **NO fake fallback** (no "reports by same country", no "reports with overlapping tags"). | D10-family invariant lifted from PR #14 — empty as first-class is cleaner to pact and honest to the analyst ("no attribution data yet" vs "pretend ranking"). |
| **D9** | Response shape | **Full `ReportListResponse` reused verbatim — `{items: ReportItem[], next_cursor: str \| null}`. NO `total`, NO `limit` echo in the body.** The envelope is keyset-only (confirmed at `api.schemas.read:177-210`), not offset-shaped like `ActorListResponse`. FE reuses `ListTable` / `ReportItem` row components exactly. | Precise DTO reuse — no new envelope, no second `COUNT(*)` query, no pact drift risk from a "total" that doesn't exist. Matches PR #11 Group C keyset envelope exactly. |
| **D10** | Actor 404 branch | **Validate actor id exists FIRST** — `SELECT 1 FROM groups WHERE id = :id` (or reuse `detail_aggregator._actor_exists` helper). If absent → `404 {"detail": "actor not found"}` identical to the existing `/actors/{id}` 404. | Consistent with PR #14's detail 404 contract. Avoids returning `{items: []}` for a truly-missing actor (which would be indistinguishable from a real-but-empty actor). |
| **D11** | `confidence` column surface | **Dropped from the response this slice.** Schema has it, but ETL confidence-population is not yet validated; surfacing as attribution signal is premature. | Follow-up carried. Re-add when a confidence-calibration pass has been done. |
| **D12** | D11-carry regression guard | **`/api/v1/actors/{id}` detail shape STAYS IDENTICAL.** `ActorDetail` DTO gets no new field. `actorDetailSchema` strip-mode invariant unchanged. The "reports-like key on ActorDetail → stripped" test from PR #14 stays green. **Reports come from a sibling endpoint, not from enriching the detail.** | Preserves PR #14 D11's multi-layer absence guarantee for the detail shape — which is exactly why D11 said "needs its own endpoint". Keeps FE/BE drift surface small. |
| **D13** | FE panel placement | **Below codenames on `ActorDetailPage`.** Keyed on `(actorId, filters, cursor)`. Not memoized across route change (new actor → new query). Panel testid `actor-linked-reports-panel`; no reports → dedicated empty card with testid `actor-linked-reports-empty` + positive no-row assertion. | Follows `SimilarReportsPanel` pattern from PR #14 Group F (memory `pattern_d10_empty_as_first_class_state`). Keyed on actor.id only (not actor.name) because id is the stable navigation anchor. |
| **D14** | Pact interactions | **+2 interactions: populated + empty.** Literal pinned-id paths. Populated body shape = `{items: [...≥3 ReportItem...], next_cursor: null}` (final page). Empty body shape = `{items: [], next_cursor: null}`. Populated uses `ACTOR_DETAIL_FIXTURE_ID=999003` (seeded by PR #14 Group G) — extend its provider-state to seed ≥3 linked reports via codename. Empty uses new `ACTOR_WITH_NO_REPORTS_ID=999004` with codenames but zero `report_codenames` rows. | Literal pinned-id paths beat regex (PR #14 Group G precedent — memory `pattern_pact_literal_pinned_paths`). Separate `.given(...)` handlers so empty and populated don't share state. Body shape matches D9 — no `total` or `limit` echo. |
| **D15** | Actor filter semantics | **Actor existence check runs FIRST, before the reports query.** Branch tree: **(a)** actor id not in `groups` → `404 {"detail": "actor not found"}`. **(b)** actor exists + no codenames → `200 {items: [], next_cursor: null}`. **(c)** actor exists + codenames exist + no `report_codenames` rows → `200 {items: [], next_cursor: null}`. **(d)** actor exists + codenames exist + reports linked but date filter excludes all → `200 {items: [], next_cursor: null}`. **(e)** happy → `200 {items: [...], next_cursor: "..." or null}`. **(a) must not be confused with (b/c/d)** — the 404 vs 200-empty distinction is load-bearing for analyst UX ("unknown actor" ≠ "known actor with no evidence yet"). | Directly extends D8/D10. Branches (b), (c), (d) are behaviorally equivalent (all render the empty panel) but semantically distinct — keep them collapsed into the same 200-empty to avoid over-specifying. |
| **D16** | Ordering + cursor pair | **`ORDER BY reports.published DESC, reports.id DESC`** — identical to `/reports` list (PR #11 Group C). **Cursor pair is `(published, id)`; seek condition is `(reports.published, reports.id) < (:cursor_published, :cursor_id)`** as a SQL row-value comparison. Same pagination codec (`api.read.pagination.encode_cursor` / `decode_cursor`) — no new cursor semantics. | Reuse guarantees test symmetry with `/reports` cursor-stability scenarios (PR #11 Group K scenario 5). Any future tiebreak change on `/reports` automatically propagates. |
| **D17** | Dedup method (query pattern lock) | **EXISTS subquery over `report_codenames JOIN codenames`, not `DISTINCT` over a multi-JOIN result.** Final query shape: `SELECT <ReportItem cols> FROM reports WHERE EXISTS (SELECT 1 FROM report_codenames rc JOIN codenames c ON c.id = rc.codename_id WHERE rc.report_id = reports.id AND c.group_id = :actor_id) AND reports.published BETWEEN :df AND :dt AND (reports.published, reports.id) < (:cp, :ci) ORDER BY reports.published DESC, reports.id DESC LIMIT :limit`. Guarantees one-report-one-row natively (no join fan-out to dedup) + works identically on PG and SQLite (standard SQL). Cursor pair comparison is unambiguous because rows are unique. | PR #11 Group C precedent for `/reports` tag/source dedup. DISTINCT over a JOIN produces correct row count but the cursor pair can match duplicate rows mid-page; EXISTS sidesteps entirely. Portability verified (EXISTS + tuple comparison both standard SQL across PG and SQLite). |
| **D18** | Panel scope | **`ActorLinkedReportsPanel` mounts ONLY on `ActorDetailPage`.** No dashboard reuse, no `/reports` list page reuse, no card-widget extraction. Out of this slice: reverse-direction panels (report → actors mentioned), filter-store integration (TLP/date-range coupling), user-selectable k or limit. | Tight slice. A reusable variant is a later refactor once the panel has shipped and real UAT shapes the cross-page needs. Matches PR #14 Group F `SimilarReportsPanel` scope discipline. |

### 2.1 Open Items — RESOLVED (1-round discuss-phase 2026-04-19)

All six items locked as recommended:

- **OI1 → A (Nested `GET /api/v1/actors/{id}/reports`).** Independent bucket, narrower filter surface, easier D8-style empty, doesn't widen the PR #11-locked `/reports` filter set. Codified in **D1**.
- **OI2 → A (Minimal filter — date + cursor + limit only).** Primary ask is "which reports mention this actor"; secondary filtering is follow-up. Codified in **D2**.
- **OI3 → A (`confidence` dropped).** ETL-side confidence population unvalidated; surfacing premature. Codified in **D11**.
- **OI4 → A (+2 pact interactions: populated + empty).** D8 empty is a contract invariant; provider state must prove 200 + empty is reachable. Codified in **D14**.
- **OI5 → A (Lighthouse target added).** One more row in README targets table; same `LH_REPORTS_SUBDIR` idiom; reviewer-side multi-target loop picks it up.
- **OI6 → A (route in `actors.py`) with structural split — query lives in `api.read.actor_reports` module, NOT in `detail_aggregator.py`.** Route location and query location separated: `actors.py` file stays at ~250 lines (within coding-style target), and the new module is a sibling of `similar_service.py` in terms of naming + responsibility ("list-service" semantics, not "detail aggregation"). Tests for the new module live at `services/api/tests/unit/test_actor_reports.py`.

---

## 3. Scope

### In scope — BE

- `services/api/src/api/routers/actors.py` — `GET /{actor_id}/reports` route + OpenAPI `responses` block (200/401/403/404/422/429 with examples). `response_model=ReportListResponse` (D9 reuse, no new envelope).
- `services/api/src/api/read/actor_reports.py` *(NEW)* — `get_actor_reports(session, *, actor_id, date_from, date_to, cursor, limit) -> ReportListResponse | None` with EXISTS-based dedup + keyset cursor + actor-exists precheck. Returns `None` when actor id missing (router maps to 404 per D10/D15). Internal `_actor_exists(session, actor_id)` helper scoped to the module.
- `services/api/src/api/schemas/read.py` — **no new DTO** (D9 reuse `ReportListResponse`). Add module-level constants `ACTOR_REPORTS_DEFAULT_LIMIT = 50`, `ACTOR_REPORTS_MAX_LIMIT = 200` (match `/reports`).
- `services/api/src/api/routers/pact_states.py` — `ACTOR_WITH_NO_REPORTS_ID = 999004` constant; extend `_ensure_actor_detail_fixture` (or add sibling `_ensure_actor_with_reports_fixture`) to seed ≥3 reports linked via codename to actor 999003; new `_ensure_actor_with_no_reports_fixture` seeds actor 999004 with codenames but zero `report_codenames` rows; 2 new `.given(...)` branches
- `services/api/tests/unit/test_actor_reports.py` *(NEW)* — per-module tests: happy path, EXISTS dedup (report linked via 3 codenames → 1 row per D17), date filter inclusive on both ends, cursor advance including the D17 tuple-comparison tiebreak, 404 branch via `None` return, 4 empty-state branches per D15 (no codenames / no report_codenames / filter excludes / happy-but-last-page)
- `services/api/tests/integration/test_detail_routes.py` — real-PG tests for the new route (gated on `POSTGRES_TEST_URL`), including the rate-limit bucket proof (drain `/actors/{id}/reports` ≠ drain `/reports` even for same user per D6)
- `services/api/tests/integration/test_pact_state_fixtures.py` — idempotency + shape test for the 2 new states
- `contracts/openapi/openapi.json` — regenerated (30 paths → 31)

### In scope — FE

- `apps/frontend/src/features/actor/useActorReports.ts` *(NEW)* — React Query hook keyed on `(actorId, filters, cursor)`; enable-guard `Number.isInteger(actorId) && actorId > 0` mirroring the detail hooks
- `apps/frontend/src/features/actor/ActorLinkedReportsPanel.tsx` *(NEW)* — 4-state render (loading / error+retry / **empty card** / populated list). Row click → `<Link to="/reports/:id">`. Positive no-row assertion on empty state.
- `apps/frontend/src/features/actor/__tests__/{useActorReports,ActorLinkedReportsPanel}.test.tsx` — hook + panel unit tests
- `apps/frontend/src/routes/ActorDetailPage.tsx` — mount `ActorLinkedReportsPanel` below codenames `<dl>`; panel receives `actor.id` only. D12 regression: `ActorDetail` render branches stay unchanged except this new mount. Testid `actor-linked-reports-panel` pinned.
- `apps/frontend/src/routes/__tests__/ActorDetailPage.test.tsx` — update: existing "no reports section" assertions REPLACED with "linked-reports panel mounts + strip-mode pin still holds on actorDetailSchema" + "D12 regression: ActorDetail shape unchanged". Add integration test: happy + empty + 4xx branches.
- `apps/frontend/src/lib/api/schemas.ts` — new `actorReportsResponseSchema` — same shape as `reportListResponseSchema` but exported separately for clarity; alternatively re-export (finalized in Group D)
- `apps/frontend/src/lib/api/endpoints.ts` — `getActorReports(actorId, filters, cursor?)` helper
- `apps/frontend/src/lib/queryKeys.ts` — `actorReports(actorId, filters, cursor?)` key factory; `serializeActorReportsFilters` mirror
- `apps/frontend/src/lib/api/__tests__/schemas.test.ts` + `endpoints.test.ts` — schema parse + endpoint helper tests
- `apps/frontend/src/lib/__tests__/queryKeys.test.ts` — key shape tests (no filter-store leak)
- `apps/frontend/tests/contract/frontend-dprk-cti-api.pact.test.ts` — +2 interactions (populated + empty) at literal paths `/api/v1/actors/999003/reports` + `/api/v1/actors/999004/reports`
- `apps/frontend/tests/contract/README.md` — coverage table 13 → 15 interactions; pinned-id registry row for `ACTOR_WITH_NO_REPORTS_ID=999004`
- `apps/frontend/lighthouse/README.md` — +1 target row (actor 999003 WITH populated linked-reports panel), updated multi-target loop
- `apps/frontend/src/i18n/{en,ko}.json` — new key group `actor.linkedReports.{title, empty, error}` (ko + en), following the `similar.*` precedent from PR #14 Group F

### Out of scope

- `/search` hybrid, attribution graph, correlation, CVE, geopolitical (other Phase 3 slices)
- `/reports?actor_id=N` filter extension on the existing list endpoint
- `report_codenames.confidence` surface (D11 carry)
- Reverse direction: `/reports/{id}` → "actors mentioned" (needs group-linking logic)
- ActorDetail charts, bulk operations, editing
- Embedding-based "similar actors" surface

---

## 4. Groups (proposed)

Order A → B → C → D → E → F → G, with B independent of A (can parallel if the aggregator is stable first).

| Group | Scope | Target size |
|:---:|:---|:---:|
| **Plan lock** | Lock plan doc after 1-round discuss-phase — freeze D1-D14, resolve OI1-OI6 | — |
| **A (BE read module)** | New `api.read.actor_reports` module with `get_actor_reports` (EXISTS dedup per D17 + keyset cursor per D16 + 4-branch empty-contract per D15 + date filter + actor-exists precheck returning None); unit tests at `test_actor_reports.py` | ~500-800 LOC |
| **B (BE route)** | `/actors/{id}/reports` endpoint on `actors.py` with rate limit + OpenAPI `responses`; integration tests (sqlite + real-PG) | ~300-500 LOC |
| **C (BE pact states)** | 2 new `.given(...)` handlers + `ACTOR_WITH_NO_REPORTS_ID=999004` constant + extend `_ensure_actor_detail_fixture` to seed linked reports; idempotency tests | ~300-400 LOC |
| **D (FE client layer)** | `actorReportsResponseSchema`, `getActorReports`, `useActorReports`, query keys + filter serializer; hook/schema/endpoint unit tests; D12 regression test on `actorDetailSchema` strip-mode staying green | ~600-800 LOC |
| **E (FE panel + page mount)** | `ActorLinkedReportsPanel` with 4 render states; mount on `ActorDetailPage`; updated `ActorDetailPage.test.tsx` with happy/empty/error/4xx branches + D12 regression + no-row positive assertion; i18n keys | ~500-800 LOC |
| **F (contract +2)** | +2 pact interactions (populated + empty) + README coverage refresh + regenerate pact JSON | ~200-300 LOC |
| **G (Lighthouse target)** | +1 row in targets table + subdir pattern for actor-with-reports; NOT a CI gate | ~50-100 LOC |

Post-group: push → open PR → CI 11/11 × 2 triggers → Codex cross-verify → address findings → merge commit.

---

## 5. Testing strategy

### 5.1 Unit coverage (BE)

- `get_actor_reports` happy path (3 reports, 2 linked to actor via 1 codename each)
- **D17 EXISTS dedup** (1 report linked via 3 codenames → 1 row in response, not 3)
- **D15(a) 404 branch** — returns `None` when actor id does not exist in `groups` (router maps to 404)
- **D15(b) empty** — actor exists with zero codenames
- **D15(c) empty** — actor has codenames but zero `report_codenames` rows
- **D15(d) empty** — date filter excludes all candidate reports
- **D16 ordering + cursor pair** — `(published DESC, id DESC)` tiebreak holds; tuple comparison `(p, id) < (cp, ci)` advances page without dup/skip even with equal-date reports
- Date filter (inclusive on both ends per `/reports` list semantics)
- Cap enforcement: `limit=200` max, `limit=0` rejected at FastAPI layer (422)
- **D6 rate limit bucket independence** — drain `/reports` → `/actors/{id}/reports` bucket still full (slowapi per-route scope)
- **D12 regression** — `ActorDetail` DTO shape unchanged (explicit schema introspection test)

### 5.2 Integration coverage (BE, real-PG gated)

- Real-PG cursor stability under concurrent insert (mirrors PR #11 Group K scenario 5)
- 60/min rate limit + headers + per-route scope
- 422 on invalid limit/cursor/date
- 404 on unknown actor id
- Happy path 200 with realistic linked reports (≥3)

### 5.3 Contract coverage

- Pact interaction 1: `GET /api/v1/actors/999003/reports` returns `{items: [...≥3 reports...], limit: 50, next_cursor: null, total: 3}` with type-only matchers on items
- Pact interaction 2: `GET /api/v1/actors/999004/reports` returns `{items: [], limit: 50, next_cursor: null, total: 0}` with literal empty body (cannot use `eachLike` for empty — PR #14 Group G precedent)
- Provider-state `idempotency` tests (shared constraint with PR #14 Group C/G)

### 5.4 FE coverage

- Schema parse: happy + empty + rejection of bad shapes (negative id, non-string title, etc.)
- Hook: fetch triggered when `actorId > 0`; not triggered when 0/negative/null; cursor advance
- Panel: 4 render states each pinned by testid; positive no-row assertion on empty; error card `role=alert` + retry button
- Page: panel mounts on populated actor; page-level test for empty actor (panel renders empty card, page still shows codenames section)
- D12 regression: `actorDetailSchema` still has no reports-like key (strip-mode invariant test unchanged); `ActorDetail` render branches unchanged except the new panel mount

### 5.5 E2E / Lighthouse

- Playwright deep-link spec: navigate to `/actors/999003` → linked-reports panel renders ≥1 row → click row → `/reports/:id` loads. Reuses pact-state seeded env.
- Lighthouse: new target `actor-999003-linked-reports` in README multi-target loop. Not a CI gate.

---

## 6. Risk & non-risk notes

### Risks

- **EXISTS vs cursor interaction** — locked by D17. EXISTS guarantees one-report-one-row natively so the `(published, id)` cursor pair is unambiguous. DISTINCT-over-JOIN was explicitly rejected because the cursor pair can match duplicate rows mid-page (correctness hazard).
- **ActorDetail shape accidentally changes** — if Group D / E accidentally adds a `linked_reports` field to `actorDetailSchema` or `ActorDetail` DTO, D12 breaks silently. Mitigation: explicit regression test on the unchanged shape before the panel lands (Group D completes BEFORE Group E).
- **`ReportListResponse` envelope drift** — D9 reuses the existing envelope verbatim (`{items, next_cursor}` — NO `total`, NO `limit` echo). If a future reviewer assumes `total` exists in the pact or FE schema, the mismatch shows up as a pact failure, not silent drift. Pact body shapes in D14 are explicit.
- **pact-js literal pinned-id pattern** — PR #14 Group G proved this works; the new empty interaction at actor 999004 needs its own `.given(...)` handler (cannot share state with populated per memory `pattern_pact_literal_pinned_paths`).
- **Route location vs module location separation** — route in `actors.py`, query in new `api.read.actor_reports` (per OI6 resolution). Avoids cramming a list-service into the detail-aggregator module (which is scoped to single-entity shallow joins). Naming mirrors `similar_service.py`.

### Non-risks (explicit)

- **Schema migration** — not needed. `report_codenames` + index already present.
- **Rate limit bucket conflation** — slowapi per-route precedent; no change needed to the limiter setup.
- **Cache layer** — no Redis cache on this surface (unlike `/similar` which needed it for embedding cost). Actor-reports is a single JOIN; PG handles it natively. Re-introduce cache only if p95 measurements say so.

---

## 7. Success criteria

- [ ] CI 11/11 green × 2 triggers (push + PR-open), no skips beyond the locked `POSTGRES_TEST_URL` + `PACT_PROVIDER_BASE_URL` baselines
- [ ] Codex review clean (≤ 1 round expected; PR #14 Codex R1 CLEAN precedent stands)
- [ ] BE unit/contract 477 → ~510 passing (no regressions from new module + route + pact states)
- [ ] FE vitest 465 → ~510 passing
- [ ] FE pact 13 → 15 interactions
- [ ] OpenAPI snapshot 130 KB → ~140 KB range, 30 → 31 paths (watch threshold still 200 KB per plan §7)
- [ ] D11 carry fully closed — PR #14 followup item "ActorDetail → reports via `report_codenames`" moves from `followup_todos.md` "From PR #14" to "Closed by PR #15"
- [ ] **D9 envelope exact reuse** — pact body shapes and FE Zod schemas match `ReportListResponse` verbatim; no `total`/`limit` echo keys anywhere
- [ ] **D12 regression guard green** — `ActorDetail` DTO/schema shape unchanged; strip-mode invariant test still passes
- [ ] **D15 four empty branches all pinned** — missing actor / no codenames / no report_codenames / date-filter-excludes all verified at unit + integration levels
- [ ] **D17 dedup pattern green** — report linked via N codenames appears exactly once (tested at N=1 and N=3)
- [ ] **D18 scope held** — `ActorLinkedReportsPanel` imports and mounts checked; no unexpected cross-page imports
- [ ] Lighthouse harness targets table +1 row; reviewer-side artifact attachment deferred per D6 (non-CI-gate)
- [ ] Merge as merge commit (NOT squash) — per collab style memory

---

## 8. References

- `docs/plans/pr14-detail-views.md` — predecessor; D11 carry defined here
- `services/api/src/api/read/detail_aggregator.py` — `get_actor_detail` (unchanged by this PR — D12 invariant)
- `services/api/src/api/read/actor_reports.py` *(new in this PR)* — where the new query lands
- `services/api/src/api/read/similar_service.py` — sibling naming precedent for new module
- `services/api/src/api/routers/actors.py` — where the new route lands
- `services/api/src/api/schemas/read.py:177-210` — `ReportListResponse` envelope (D9 reuse target)
- `services/api/src/api/read/pagination.py` — `encode_cursor` / `decode_cursor` (D16 reuse)
- `db/migrations/versions/0001_initial_schema.py:127-132` — `report_codenames` schema
- `db/migrations/versions/0002_staging_and_indexes.py:165-171` — `ix_report_codenames_codename_id`
- Memory `pattern_pact_literal_pinned_paths` — literal paths + ON CONFLICT upsert
- Memory `pattern_d10_empty_as_first_class_state` — empty-state render contract
- Memory `pitfall_pinned_id_vs_unique_name` — `groups.name` UNIQUE interaction with pinned id fixtures

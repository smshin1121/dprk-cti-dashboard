# PR #17 — Phase 3 slice 3: `/api/v1/search` FTS-only MVP (hybrid ranking deferred)

**Status:** 🔒 **Locked 2026-04-19** — Draft v2 after 1-round discuss-phase. D1–D18 frozen; OI1–OI8 resolved A/A/A/A/**B**/A/A/A. **OI5 = B flipped**: llm-proxy has NO embedding endpoint today (`services/llm-proxy/src/llm_proxy/routers/provider.py` exposes only `GET /api/v1/provider/meta`; `services/llm-proxy/src/llm_proxy/main.py:66` mounts only that router). Query-time embedding generation is therefore structurally unavailable — this slice ships **FTS-only**. Hybrid fusion (RRF + pgvector) is deferred to a future slice after an llm-proxy infra PR adds the embedding adapter.

**Base:** `main` at `c341256` (PR #16 Node 20 GHA bump merged).

**Mapping to design doc v2.0 §4/§5/§7:**
- §5 L580 originally specifies `/search` as "전문검색 + 벡터 하이브리드". This slice partially delivers (FTS half only); the vector-hybrid half is **explicit carry** below.
- §4 L614: ⌘K Command Palette primary UX consumer (locks in PR #13 D3 are preserved).
- §7.7 L601/719: p95 ≤ 500ms SLO. With vector path removed, re-tightened to **p95 ≤ 250ms** (D12) for this MVP — FTS-only is structurally faster than hybrid.

---

## 1. Goal

Ship an FTS-only MVP of `/api/v1/search` and wire it to the existing `⌘K` CommandPalette, leaving the hybrid-fusion follow-up with a clear integration seam.

1. **BE**: `GET /api/v1/search?q=<query>&limit=<N>` returning report hits ranked by PostgreSQL FTS `ts_rank_cd` against the existing `ix_reports_title_summary_fts` GIN index.
2. **FE**: wire `⌘K` CommandPalette to surface live `/search` results (debounced), keeping ALL existing PR #13 palette commands intact.
3. **Contract**: +3 pact interactions (populated + empty + 422).
4. **Observability**: structured `search.query` log + envelope-level `latency_ms` so the p95 budget is verifiable without digging into traces.
5. **Follow-up seam**: the envelope includes a reserved-nullable slot for vector rank (`vector_rank: null` this slice) so adding the vector half later is an additive change on the envelope, not a re-shape.

### Explicit non-goals (deferred to follow-up PRs)

- **Hybrid ranking / RRF fusion** — requires query-time embedding generation; llm-proxy needs an embedding endpoint first. Separate infra PR → separate feature PR in that order.
- **Query-time embedding generation** — blocked on llm-proxy readiness.
- **pgvector kNN participation in `/search`** — depends on the above.
- Multi-entity search (codenames / incidents / alerts)
- Query suggestions / autocomplete
- Spellcheck / typo-tolerance (pg_trgm fuzzy dial)
- Re-ranking (cross-encoder, LLM) — Phase 4
- Saved searches / search history
- `/search` as a standalone page (palette-only this slice)
- Extra filter dimensions beyond date range (tag / source / tlp)

---

## 2. Decisions — LOCKED 2026-04-19

| ID | Item | Locked | Rationale |
|:---:|:---|:---|:---|
| **D1** | Entity scope | **reports only**. Codenames / incidents / alerts deferred to their own PRs. | Keep the slice bounded; reports is the richest indexable corpus and the primary analyst target. Cross-entity composition is a post-baseline question. |
| **D2** | Ranking method | **FTS `ts_rank_cd` only** (was RRF hybrid in Draft v1). Sort `ts_rank_cd DESC, reports.id DESC` for stable order on equal scores. | OI5 resolution — no vector path this slice. `ts_rank_cd` is close-to-BM25 ranking over the `'simple'` dictionary tsvector and suffices for MVP relevance. Follow-up PR adds RRF over `(fts_rank, vector_rank)` once embedding endpoint exists. |
| **D3** | BM25 source | **PostgreSQL FTS `ts_rank_cd`** over the existing `ix_reports_title_summary_fts` GIN index (migration 0001:101). Zero new infra. | Confirmed — the GIN index over `to_tsvector('simple', title \|\| ' ' \|\| summary)` is already installed. |
| **D4** | ~~Vector search source~~ | **DEFERRED to follow-up** — vector path NOT in this slice. `reports.embedding vector(1536)` column exists (PR #14 `/similar` uses it) but `/search` doesn't touch it this PR. | OI5 = B: llm-proxy lacks an embedding endpoint. Attempting to wire a vector path without query-time embedding would force either (a) a hardcoded stub or (b) pulling llm-proxy infra work into this slice. Both blur the scope. |
| **D5** | Empty query behavior | `q=` empty, whitespace-only, or missing → **`422`** with FastAPI-shaped body `{detail: [{loc: ["query", "q"], msg: "q must not be empty", type: "value_error.missing"}]}`. | Consistent with plan D12 uniform-422 precedent (PR #11 / #14 / #15). Empty-query "return everything" is what `/reports` list is for. |
| **D6** | Rate limit | **60/min per-user per-route** via slowapi. | Inherited lock. |
| **D7** | RBAC | **5 read roles** (analyst / researcher / policy / soc / admin). | Inherited lock. |
| **D8** | Filter surface | **`date_from` + `date_to` only**. No tag / source / tlp / group_id / actor_id. | OI3 = A. Minimal slice; filter widening is analyst-UAT territory for a follow-up. |
| **D9** | Response envelope | **New DTO**: `{items: SearchHit[], total_hits: int, latency_ms: int}` where `SearchHit = {report: ReportItem, fts_rank: float, vector_rank: null}`. The `vector_rank` key is **present as a literal `null`** in every response this slice — reserves the envelope slot for the follow-up hybrid path so adding it later is additive on the JSON schema, not a re-shape. | OI4 = A with Draft v2 simplification. `fts_rank` replaces Draft v1's `rrf_score + bm25_rank + vector_rank` trio. `vector_rank: null` is the forward-compat slot: FE/Zod accepts null now and will accept integer later without schema churn. |
| **D10** | Empty-result contract | **`200 + {items: [], total_hits: 0, latency_ms: ...}`** when the query matches no reports. NOT 404, NOT 500, NO fake fallback. | D10-family invariant (PR #14 `/similar`, PR #15 `/actors/{id}/reports`). |
| **D11** | Cache | **Redis cache keyed on `(q_lower, date_from, date_to, limit)` with 60s TTL**. Hit → serve + `cache_hit=true` log. Miss → compute + store. Graceful degrade on `RedisError` (log + compute). **Empty results ARE cached too** (OI6 = A). | Search is bursty (palette keystrokes, especially post-debounce when user re-opens the palette). 60s dedupes the "typed 'laza' → 'lazar' → 'lazaru'" tail. |
| **D12** | Latency budget (re-tightened) | **Server-side p95 ≤ 250ms** (was 500ms in Draft v1 for hybrid; FTS-only can be tighter). Sub-budgets: **FTS ≤ 150ms + fusion/envelope ≤ 50ms + cache/serialization ≤ 50ms**. Envelope `latency_ms` logs the total; log line breaks it down (D16). | Draft v1's 500ms was sized for hybrid (BM25 + embedding + vector + fusion). With only FTS, the budget tightens. If the FTS path exceeds 150ms at p95 post-launch, the fix is in the index / query shape, not in "maybe cache it harder". |
| **D13** | Result cap | `limit ∈ [1, 50]`, default **10**. | Matches `/similar`. 50 max room for palette "show more". |
| **D14** | Pact interactions | **+3**: (a) populated `q=lazarus` with literal path `/api/v1/search?q=lazarus`; (b) D10 empty `q=nomatchxyz123`; (c) D5 422 `q=` (empty). All literal query strings — pact-js V3 regex-on-query-string is as risky as regex-on-path (PR #14 Group G R3 mitigation carries). **Body shape** reflects D9 with `vector_rank: null` in the populated example so verifier exercises the forward-compat slot. | OI8 = A. Three interactions cover the happy / empty / 422 state machine. Provider states: (a) seeds 3 reports matching `lazarus` in FTS vocabulary; (b) FTS-empty fixture (reports seeded but none match the keyword); (c) no seed (FastAPI 422 fires before handler). |
| **D15** | ~~Embedding backfill degraded path~~ | **NOT APPLICABLE this slice** (was active in Draft v1 with `reports.embedding` ≥ 50% NULL → FTS-only fallback). With vector path deferred, the "FTS-only fallback" IS the full behavior; no conditional branching. | Reinstated as a live decision when the hybrid follow-up lands. |
| **D16** | Structured log line | One log line per request: `{event: "search.query", q_len, hits, latency_ms, fts_ms, cache_hit}`. NO `vector_ms` / `embedding_ms` / `degraded` fields this slice (OI5 = B removed the corresponding sub-stages). No raw `q` text (PII-adjacency — actor names / IoCs leak risk). Only `q_len`. | OI5 resolution — simpler log surface. When the follow-up hybrid PR ships, it will add `vector_ms` + `embedding_ms` as new fields; existing aggregators that consume this log won't break (additive only). |
| **D17** | FE Command Palette integration | **Debounced 250ms `q` input → `useSearchHits(q, filters)` hook → results section BELOW existing 7 PR #13 D3 commands**. Empty `q` → commands only (no API call). Clicking a result → `<Link to="/reports/:id">`. **PR #13 D3 palette scope locked** — the 7 local commands (4 nav + theme + clear-filters + sign-out) stay exactly as-is; search results are additive. | OI7 = A (250ms standard keystroke timing; matches Linear/Notion). |
| **D18** | URL state | **No new `URL_STATE_KEYS` entries.** PR #13's 5-key whitelist (`date_from / date_to / group_id / view / tab`) stays locked. `q` is palette-ephemeral. Static-source scope-lock test pins it (same pattern as PR #15 Group E `scope-lock.test.ts`). | Search in ⌘K is not route state. Deep-linkable search pages are a separate follow-up with their own URL-state contract. |

### 2.1 Open Items — RESOLVED (1-round discuss-phase 2026-04-19)

- **OI1 → A** (reports-only)
- **OI2 → A** (PG FTS `ts_rank_cd`)
- **OI3 → A** (date-only filter)
- **OI4 → A** (new DTO with per-hit rank metadata + envelope `latency_ms`)
- **OI5 → B** (FTS-only MVP; hybrid deferred). Confirmed by reviewer: `services/llm-proxy/src/llm_proxy/routers/provider.py` exposes only `GET /api/v1/provider/meta`; `services/llm-proxy/src/llm_proxy/main.py:66` mounts only that router. No embedding endpoint exists.
- **OI6 → A** (cache empty too — 60s TTL)
- **OI7 → A** (250ms debounce)
- **OI8 → A** (422 pact interaction included)

### 2.2 Deferred to follow-up PRs (separate slices)

1. **llm-proxy embedding endpoint** (infra PR — reviewer authorizes scope separately). Prerequisite for everything below.
2. **Query-time embedding adapter** — a `services/api/src/api/read/search_embedder.py` module (name reserved, NOT created this PR) that wraps the llm-proxy call + handles timeout/degrade.
3. **pgvector fusion path in `/search`** — once embeddings are generatable, the service adds a second rank list (reports.embedding cosine kNN) alongside the FTS rank list.
4. **RRF fusion** — Reciprocal Rank Fusion with k=60 merging the two rank lists; fills the `vector_rank` slot already present in D9.
5. **Hybrid degraded mode** (formerly Draft v1 D15) — reinstated at that time with the "embedding coverage < 50% → FTS-only fallback" semantics. Already structurally identical to THIS slice's FTS-only path, so the integration is additive.

---

## 3. Scope

### In scope — BE

- `services/api/src/api/routers/search.py` *(NEW)* — `GET /api/v1/search` route with `Query(min_length=1)` + trimmed-whitespace guard for `q`, `Query(ge=1, le=50)` for `limit`, rate limit + RBAC + OpenAPI responses (200/401/403/422/429 with examples). Date filter via `date_from` / `date_to` reusing `/reports` Query param patterns.
- `services/api/src/api/read/search_service.py` *(NEW)* — FTS orchestrator: (1) normalize `q` (trim, lower), (2) check Redis cache, (3) run PG FTS query with `plainto_tsquery('simple', :q)` + `ts_rank_cd` ordering, (4) build envelope with `latency_ms` + per-hit `fts_rank`, (5) write cache.
- `services/api/src/api/read/search_cache.py` *(NEW)* — Redis cache `search:{sha1(q+filters+limit)}` with 60s TTL; graceful `RedisError` degrade; pure `cache_key(*, q, date_from, date_to, limit) -> str` for testability.
- `services/api/src/api/schemas/read.py` — +2 DTOs (`SearchHit`, `SearchResponse`) + module constants `SEARCH_LIMIT_MIN=1 / MAX=50 / DEFAULT=10` + `SEARCH_CACHE_TTL_SEC=60`.
- `services/api/src/api/routers/pact_states.py` — 2 new `.given(...)` handlers: `_ensure_search_populated_fixture` (seeds 3 reports whose title + summary contain `lazarus` in FTS-recognizable form) + `_ensure_search_empty_fixture` (seeds reports that match NO `nomatchxyz123` query — distractor corpus so "empty" is real, not DB-wide emptiness). New constants `SEARCH_POPULATED_FIXTURE_REPORT_IDS = (999060, 999061, 999062)` + `SEARCH_EMPTY_FIXTURE_REPORT_IDS = (999063,)` (distractor).
- `services/api/tests/unit/test_search_service.py` *(NEW)* — unit tests: cache hit/miss, FTS empty (D10), FTS ordering (higher rank first), `q` normalization (trim/lower), `vector_rank` always null this slice.
- `services/api/tests/integration/test_search_route.py` *(NEW)* — sqlite integration: happy / empty / 422 (3 input shapes) / RBAC 5-role / rate limit bucket.
- `services/api/tests/integration/test_pact_state_fixtures.py` — +2 real-PG gated tests for the new search fixtures + pinned-id constants drift test in `test_search_service.py` (unconditional, same pattern as PR #15 Group C).
- `contracts/openapi/openapi.json` — regenerated (31 paths → 32).

### In scope — FE

- `apps/frontend/src/features/search/useSearchHits.ts` *(NEW)* — React Query hook; 250ms debounce via `useEffect + setTimeout + clearTimeout`; enable guard `q.trim().length > 0`; `staleTime: 30_000`.
- `apps/frontend/src/features/search/SearchResultsSection.tsx` *(NEW)* — 4 render states (loading / error / D10 empty / populated); row → `<Link to="/reports/:id">`; shows envelope `latency_ms` as small meta pill.
- `apps/frontend/src/components/CommandPaletteButton.tsx` (existing) — extended: add a controlled `q` state + pass to `SearchResultsSection`; keep PR #13 D3 7 commands at the top. Escape / outside-click / editable-target guards all preserved.
- `apps/frontend/src/lib/api/schemas.ts` — +2 Zod schemas: `searchHitSchema = {report: reportItemSchema, fts_rank: z.number(), vector_rank: z.number().nullable()}` + `searchResponseSchema = {items: z.array(searchHitSchema), total_hits: z.number().int().gte(0), latency_ms: z.number().int().gte(0)}`. `vector_rank` nullable keeps forward-compat with the follow-up hybrid slot.
- `apps/frontend/src/lib/api/endpoints.ts` — `getSearchHits(q, filters, signal)` helper.
- `apps/frontend/src/lib/queryKeys.ts` — `searchHits(q, filters)` factory.
- `apps/frontend/src/features/search/__tests__/*` — unit tests for hook + section + debounce timing + D18 URL-state invariance.
- `apps/frontend/src/components/__tests__/CommandPaletteButton.test.tsx` — extended: debounce behavior, empty-q → no fetch, PR #13 D3 commands still render alongside results, Escape closes, modifier-k opens, outside-click closes.
- `apps/frontend/tests/contract/frontend-dprk-cti-api.pact.test.ts` — +3 interactions (populated / empty / 422).
- `apps/frontend/tests/contract/README.md` — coverage 15 → 18; pinned-id registry note for search fixture.

### Out of scope

- Hybrid ranking / RRF / vector path (deferred — §2.2)
- Query-time embedding generation
- Multi-entity search (codenames / incidents / alerts)
- URL state for `q`
- Query suggestions / autocomplete / spellcheck
- `/search` standalone page
- Lighthouse manual-audit target — palette-with-search reproducibility depends on debounce + API response, which Lighthouse run-audit.mjs can't easily drive; skip Group G this slice (candidate for a future follow-up if the reviewer sees value).

---

## 4. Groups (proposed)

Reduced from Draft v1 because there's no embedder/vector-service work. 7 Groups total.

| Group | Scope | Target size |
|:---:|:---|:---:|
| **Plan lock** | Freeze D1-D18 + OI1-OI8; this document | — |
| **A (BE service)** | `search_service.py` + `search_cache.py` + schema DTOs + module constants; unit tests including cache key stability + FTS ordering + D10 empty + `vector_rank` always null | ~500-700 LOC |
| **B (BE route)** | `search.py` router + OpenAPI responses + D5 422 + D6 rate limit + D7 RBAC + D8 date filter; sqlite integration tests (3 422 shapes + RBAC 5-role + rate limit bucket proof) | ~400-550 LOC |
| **C (BE pact states)** | 2 new `.given(...)` handlers + constants + fixture helpers; real-PG gated tests + unconditional constant-drift test | ~400-500 LOC |
| **D (FE client)** | Zod + endpoint + hook (with debounce) + queryKeys + D18 URL-state invariance test | ~500-700 LOC |
| **E (FE palette integration)** | `SearchResultsSection` + CommandPalette extension preserving PR #13 D3 scope; 4 render states; integration test proving existing commands unaffected | ~600-800 LOC |
| **F (contract)** | +3 pact interactions + README refresh + pact JSON regen | ~300-400 LOC |

Post-group: push → PR → CI 11/11 × 2 green → Codex cross-verify → merge.

---

## 5. Testing strategy

### 5.1 Unit (BE)

- **D2 FTS ordering** — hand-seeded reports with distinct keyword density produce stable `ts_rank_cd DESC, id DESC` output
- **D9 `vector_rank: null`** — every SearchHit this slice has `vector_rank == None`; regression guard so a future refactor doesn't silently drop the forward-compat slot
- **D10 empty result** — zero FTS matches → `{items: [], total_hits: 0, latency_ms >= 0}`
- **D11 cache hit/miss** — SHA1 key stability across identical inputs; graceful `RedisError` degrade logs + computes; empty results cached too (OI6)
- **`q` normalization** — `"  LazArUs  "` + `"lazarus"` produce identical cache keys (trim + lower)
- **D12 latency breakdown** — `latency_ms` on envelope equals `fts_ms` + overhead within tolerance; cache-hit path has `fts_ms=0`
- **D16 log line** — `q` text never appears; only `q_len`

### 5.2 Integration (BE)

- Happy: sqlite with seeded reports; envelope shape + ordering
- 422: empty `q` + whitespace-only `q` + `limit=0` + `limit=51`
- RBAC: 5 roles pass, 401 no-cookie, 403 unknown role
- Rate limit: drain `/search` bucket; `/reports` bucket unaffected (per-route scope)
- Real-PG (gated): seeded FTS fixtures, `ts_rank_cd` ordering verified against real GIN index

### 5.3 Contract

- Populated `q=lazarus`: `eachLike(SearchHit)` with `fts_rank` as `decimal` / `vector_rank` as literal `null` + envelope `total_hits / latency_ms` as `integer`
- Empty `q=nomatchxyz123`: literal `{items: [], total_hits: 0, latency_ms: integer(1)}`
- 422 `q=` (empty): FastAPI error body literal shape
- Provider-state idempotency + constant-drift tests (same pattern as PR #15 Group C)

### 5.4 FE

- Schema parse: happy + empty + `vector_rank: null` + `vector_rank: 7` (forward-compat)
- Hook: debounce (1 fetch after 250ms of idle, not per-keystroke); enable guard on empty/whitespace q; filter toggles don't refetch
- Palette section: 4 states pinned; existing PR #13 D3 commands still render at top; D10 empty → no item testids
- CommandPalette existing contract: `mod+k` opens, Escape closes, outside-click closes, editable-target guard skips typing
- **D18 regression**: `URL_STATE_KEYS` unchanged; no `q` / `search` / `query` leaf keys

### 5.5 E2E

- Playwright spec: open palette → type `lazarus` → results appear after debounce → click row → `/reports/:id` loads

---

## 6. Risk & non-risk notes

### Risks

- **`'simple'` FTS dictionary is unstemmed** — `"attacks"` won't match `"attack"`. For MVP this is acceptable. Follow-up to switch to `'english'` dictionary is a separate migration (touches the GIN index) — NOT this slice.
- **PG FTS `plainto_tsquery` vs `websearch_to_tsquery`** — the former sanitizes input so `q='laz & "rus"` can't fail parsing; latter supports boolean ops. Use `plainto_tsquery` for MVP; boolean operators are advanced-search territory.
- **Cache key collision on whitespace-only** — `q=' '` after trim becomes `q=''`; guard against this by returning 422 BEFORE hashing (D5 gate).

### Non-risks (explicit)

- **Schema migration** — not needed. FTS + trigram + vector indexes all exist from migration 0001. `reports.embedding` untouched (D4 deferred).
- **llm-proxy integration** — explicitly OUT of scope (D4, §2.2).
- **Hybrid-vs-FTS-only conditional branching** — not present this slice. Single code path = FTS. The D9 envelope's `vector_rank: null` slot is a static literal, not a degraded-state signal.
- **Existing ⌘K palette contract** — PR #13 D3 7 commands stay exactly as-is.

---

## 7. Success criteria

- [ ] CI 11/11 × 2 triggers green; no new skips beyond locked baselines
- [ ] Codex R1 CLEAN (target — maintain PR #14/#15 precedent; 3rd PR in a row if it holds)
- [ ] BE tests ~516 → ~555 (no regression from search additions)
- [ ] FE vitest ~507 → ~545
- [ ] FE pact 15 → 18
- [ ] OpenAPI snapshot ~137 KB → ~145 KB; 31 → 32 paths
- [ ] **D9 forward-compat slot live** — every SearchHit in the populated pact carries `vector_rank: null` literal; FE Zod accepts both null and (future) integer without schema churn
- [ ] **D12 latency budget observable** — every 200 response carries `latency_ms` (envelope) + `fts_ms` (log line); cache-hit path has `fts_ms=0`
- [ ] **D17 palette scope preserved** — PR #13 D3 7 commands unchanged at the top of the palette; search results mount as a separate additive section
- [ ] **D18 URL_STATE_KEYS unchanged** — static-source scope-lock test green; `q` never in URL
- [ ] Follow-up §2.2 list explicitly recorded in memory `followup_todos.md` after merge
- [ ] Merge as merge commit (NOT squash)

---

## 8. References

- `services/api/src/api/read/similar_service.py` — Redis cache pattern (PR #14 Group B) for search cache
- `services/api/src/api/read/similar_cache.py` — cache_key purity pattern
- `services/api/src/api/read/actor_reports.py` — recent read-module naming precedent (PR #15 Group A)
- `services/api/src/api/routers/reports.py` — `/reports` filter codec for date range reuse
- `services/api/src/api/routers/search.py` — **new**
- `db/migrations/versions/0001_initial_schema.py:101` — `ix_reports_title_summary_fts` (D3 target)
- `services/llm-proxy/src/llm_proxy/routers/provider.py` — confirms ONLY `/api/v1/provider/meta` exists today (OI5 = B evidence)
- `services/llm-proxy/src/llm_proxy/main.py:66` — router mount confirming no embedding endpoint
- `DPRK_Cyber_Threat_Dashboard_설계서_v2.0.md:580` — `/search` endpoint locked in §5 (full hybrid; this slice delivers the FTS half)
- `DPRK_Cyber_Threat_Dashboard_설계서_v2.0.md:601` — 500ms p95 SLO (re-tightened to 250ms for FTS-only MVP in D12)
- Memory `pattern_pact_literal_pinned_paths` — literal query strings for pact
- Memory `pattern_d10_empty_as_first_class_state` — empty-state render contract
- Memory `pitfall_pact_js_matchers_on_headers` — why literal > regex on paths AND query strings

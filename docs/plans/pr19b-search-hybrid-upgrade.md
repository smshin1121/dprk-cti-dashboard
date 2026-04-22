# PR #19b — Hybrid `/search` upgrade (fill the `vector_rank` slot; RRF fusion; degraded mode)

**Status:** 🔒 **Locked v1.1 — 2026-04-22** (post 1-round discuss-phase + Group A pre-kickoff scope amendment — see §3.0). OI1–OI6 resolved **B / A / B / B / A / B**. No code written yet. Next: Group A (config-only) per §4 / §10.

**Base:** `main` at `e93555b` (PR #20 Windows SelectorEventLoop hotfix merged 2026-04-21).

**Why this PR exists:** PR #17 deliberately shipped `/api/v1/search` as an FTS-only MVP and reserved `SearchHit.vector_rank: int | null` for a later additive upgrade. PR #18 shipped `POST /api/v1/embedding` on `services/llm-proxy` (`main.py:97` mounts the router — OI5 blocker from PR #17 is resolved). PR #19a shipped the embed-on-ingest writer for both production insertion paths (worker bootstrap + api promote) plus the one-shot `backfill-embeddings` CLI. This PR closes PR #17 §2.2 items 2–5 in a single slice:

- Query-time embedding adapter (item 2)
- pgvector kNN as the second rank list (item 3)
- RRF fusion over `(fts_rank, vector_rank)` (item 4)
- Hybrid degraded mode (item 5)

**Execution order:** PR #19a merged 2026-04-20 → PR #20 merged 2026-04-21 → real backfill on a prod-like DB (pending — no prod DB exists yet) → THIS PR can ship. The backfill is not a CI / correctness dependency (tests seed deterministic vectors); it is an end-user quality dependency. D13 records this.

**Mapping to design doc v2.0 §5 / §7.7:**

- §5 L580: `/search` full "전문검색 + 벡터 하이브리드" semantics. PR #17 delivered the FTS half; this slice delivers the vector half + fusion and restores full scope.
- §7.7 L601 / L719: p95 ≤ 500ms SLO — restored here from PR #17's temporarily tightened 250ms (see D7).

---

## 0. Lock summary (pinned invariants)

Three lines that survive implementation debate and anchor every Group:

1. **Envelope additivity.** `SearchHit.vector_rank` flips from literal `null` to 1-indexed `int` when the hit appears in the vector-kNN top-N. No other field is added / removed / re-shaped. Pact interaction count stays 15. FE Zod unchanged. This PR is the payoff for PR #17 D9's forward-compat slot — see `pattern_fts_first_hybrid_mvp.md`.
2. **Read-path only.** `/search` reads `reports.embedding`; never writes. All embedding writes remain PR #19a's responsibility. Rows with `embedding IS NULL` are excluded from the vector path but still eligible for the FTS path.
3. **Fail-open for transient, fail-loud for permanent.** llm-proxy `429/502/503/504/timeout` on the query-embedding call → degraded mode (HTTP 200 + FTS-only + `vector_rank: null` everywhere + `degraded=true` log). llm-proxy `422` / dimensions mismatch / malformed 2xx → HTTP 500. Parity with PR #19a D5 taxonomy (`pattern_enrichment_tx_boundary_catch.md`).

OI1–OI6 locked 2026-04-22 — see §2.1. Every D-row below reads with those lock decisions applied; inline "**OI*N* locked X**" annotations flag where each lock lands in the D-table.

---

## 1. Goal

Fill PR #17's `vector_rank` slot with real hybrid retrieval without changing envelope shape.

1. `GET /api/v1/search?q=<q>` calls llm-proxy `POST /api/v1/embedding` once per uncached query → runs pgvector cosine kNN against `reports.embedding` → fuses with FTS rank via RRF (k=60) → returns a unified sorted list.
2. When llm-proxy is unavailable (transient) or `reports.embedding` coverage is structurally insufficient, the route degrades to FTS-only without changing the envelope shape or status code.
3. `vector_rank` is the only envelope field whose **value semantics** change (literal null → 1-indexed int when the hit is in the vector-kNN top-N). Field set and types are unchanged.
4. FE / Zod / Pact JSON shape: **zero shape changes**. The forward-compat slot reserved in PR #17 absorbs this additive upgrade.

### Explicit non-goals (deferred to future PRs)

- `staging` search — staging rows never indexed into `/search`.
- Multi-entity search (codenames / incidents / alerts) — PR #17 D1 lock stands.
- Query suggestions / autocomplete / spellcheck / cross-encoder rerank — Phase 4.
- Saved searches / search history.
- `/search` standalone page with its own URL-state contract.
- New filter dimensions (tag / source / tlp / group_id / actor_id).
- Query-time embedding of anything other than `q` (filter facets, etc.).
- API-side cache of the query-embedding vector. llm-proxy already caches per `(provider, model, text)` at 24h TTL; a second layer adds key-drift risk with negligible latency gain.

---

## 2. Decisions — LOCKED 2026-04-22

| ID | Item | Proposed | Rationale |
|:---:|:---|:---|:---|
| **D1** | Query-time embedding client | **Reuse existing `services/api/src/api/embedding_client.py`** (PR #19a Group B artifact). No new module. `search_service.py` imports `LlmProxyEmbeddingClient` directly at the call site. *(The `search_embedder.py` name reserved in PR #17 §2.2 item 2 is retired by §3.0 amendment — premise of the reservation was "no api-side embedding client exists", which PR #19a invalidated.)* | The existing client is already the shape this slice needs: `async def embed(texts: list[str], *, model: str | None = None) -> EmbeddingResult`. Caller passes `[q]` and unwraps `result.vectors[0]`. Adding a wrapper module whose job is "call `embed([q])` and pick index 0" is mechanical churn with zero semantic gain — Codex would flag it on first review. `pattern_service_local_duplication_over_shared.md` justifies worker-vs-api duplication, not within-service wrapping. |
| **D2** | Vector candidate set | `SELECT id, 1 - (embedding <=> :q_vec) AS vscore FROM reports WHERE embedding IS NOT NULL ORDER BY embedding <=> :q_vec ASC LIMIT :vector_k` | pgvector cosine distance. `vector_k = 50` (**OI1 locked B** — `limit ≤ 50` per PR #17 D13 makes k=10 too narrow for fusion value, k=100 overkill). Null rows explicitly excluded per §0 line 2. |
| **D3** | Fusion algorithm | RRF with `k = 60`; `score(d) = 1/(k + rank_fts(d)) + 1/(k + rank_vec(d))` where a missing rank contributes 0. Final sort: `rrf_score DESC, reports.id DESC` (stable tie-break, matching PR #17 D2). | Standard RRF constant. Pure function, no IO, fully unit-testable. |
| **D4** | Envelope field semantics | `SearchHit = {report, fts_rank: float, vector_rank: int \| null}` — exact PR #17 D9 shape. `vector_rank` = 1-indexed position in vector-kNN top-N when present, else `null`. `fts_rank` unchanged. Vector-only hits receive `fts_rank: 0.0` literal (**OI2 locked A**), with docstring + dedicated unit test pinning the "not in FTS top-N" semantic. | Envelope `fts_rank` stays non-null `float` — D12 "zero FE churn" is preserved. `ts_rank_cd` almost never returns exactly 0.0 for a matched row, so the literal-zero sentinel is distinguishable in practice. |
| **D5** | Degraded-mode trigger | OR of: (a) query-embedding call returns transient (`429/502/503/504/timeout`); (b) `reports.embedding` coverage below threshold 0.5. Both produce FTS-only response with `vector_rank: null` everywhere + `degraded=true` log field. Coverage via **process-local cache, 600s refresh interval** (**OI4 locked B** — `HYBRID_SEARCH_COVERAGE_REFRESH_SECONDS=600`). | (a) is request-scope, (b) is process-scope. Composition is a simple OR — no precedence / override. `degraded_reason ∈ {"transient", "coverage", null}` for forensic discrimination. Worst-case staleness: 10-min lag after a bulk backfill — acceptable since the lag fails degraded-when-hybrid-was-possible, never the reverse. |
| **D6** | Embedding cache reuse | No api-local cache for query embeddings. Rely entirely on llm-proxy's existing 24h `(provider, model, text)` cache. | Double-caching guarantees key drift; llm-proxy cache is already observable via its `cache_hit` field in the embedding response. Query-embedding latency on cache-hit is ~5–30ms — not worth mirroring. |
| **D7** | Latency budget | p95 ≤ 500ms end-to-end (restored from PR #17's FTS-only 250ms). FTS + embedding run in parallel via `asyncio.gather` (**OI3 locked B**) so effective p95 ≈ max(leg) rather than sum(leg). Sub-budgets: embedding ≤ 250ms (llm-proxy cache-hit path ≤ 30ms) \|\| FTS ≤ 150ms, then vector kNN ≤ 50ms + fusion + envelope ≤ 50ms sequentially. | Parallelization reclaims ~150ms on cold-cache queries. Matches design doc §7.7 L601 original SLO. Error fanout: a transient in one leg does not cancel the other — both legs awaited; transient → degraded branch with the FTS leg's result. |
| **D8** | Log line | Extend PR #17 D16 `search.query` log additively with `{embedding_ms, vector_ms, fusion_ms, degraded, degraded_reason, llm_proxy_cache_hit}`. No `q` text ever. **OI5 locked A** — `degraded` state lives in this log line only; no envelope field. | Existing D16 aggregators keep parsing — purely additive fields. `degraded_reason` value is null when `degraded=false`. Operational telemetry (logs) and product UX exposure (envelope / banner) are separated by design; the latter, if ever needed, goes to a future `/health`-style endpoint — not into `/search`'s response shape. |
| **D9** | Error taxonomy | llm-proxy `422` / dimensions mismatch / malformed 2xx → API 500 with short `{detail}`. `429/502/503/504/timeout` → 200 + degraded FTS. FTS itself erroring → 500 (unchanged from PR #17). | Parity with PR #19a `pattern_enrichment_tx_boundary_catch.md`: transient caught inside the embedder layer, permanent propagates out and becomes a visible 500. |
| **D10** | Null-embedding exclusion | SQL `WHERE embedding IS NOT NULL` on the vector path. Null rows never participate in RRF — not as zero score, not as null rank. | Structural guard. Worst case is "vector contributes nothing for this row"; never "zero vector distorts fusion". |
| **D11** | Pact interactions | **0 added.** Keep PR #17's 3 interactions. Populated interaction body value for `vector_rank` flips from literal `null` to `integer()` matcher (**OI6 locked B**); provider state additionally stamps deterministic stub 1536-dim embeddings onto the pinned fixture rows (`SEARCH_POPULATED_FIXTURE_REPORT_IDS = 999060..062`) so vector kNN places them in top-N. | Envelope shape unchanged — only one field's expected value validator shifts from literal to shape. OI6 = A was rejected because freezing `null` in the contract would turn PR #17 D9's forward-compat slot into a "forever null" lock, exactly the outcome the slot was designed to avoid. Provider-state extension cost: a single UPDATE statement per fixture row (PR #19a already provides the write path primitives). |
| **D12** | FE changes | **Zero FE source changes.** Zod already accepts `vector_rank: z.number().int().nullable()` (PR #17 D9). A new parse-regression test is added to pin both null and int acceptance explicitly. Exposing "degraded" via a UX badge is **OI5**. | Schema re-shape = 0. This is the whole point of PR #17 D9's forward-compat slot. |
| **D13** | Backfill dependency | Merge scheduling requires a backfill run with coverage > 95% on whatever prod-like DB hosts end users. Tests seed deterministic vectors so CI is independent. | Without backfill, D5(b) trips permanently and the hybrid path is effectively dead code in production. Not a correctness issue — a product-quality one. |

### 2.1 Open Items — LOCKED 2026-04-22 (1-round discuss-phase)

- **OI1 → B** (`vector_k = 50`). `A` = 10 rejected (symmetric-k loses most RRF value); `C` = 100 rejected (overkill when `limit ≤ 50` per PR #17 D13).
- **OI2 → A** (`fts_rank: 0.0` literal for vector-only hits, with docstring + unit-test pin). `B` = envelope widen rejected (breaks D12 "zero FE churn" and the D9 non-null float lock); `C` = post-filter rejected (defeats fusion's vector-only-recall value).
- **OI3 → B** (`asyncio.gather(fts, embedding)`). `A` = serial rejected (embedding is the slow leg; serial makes cold-cache p95 = sum(leg), parallel makes it ≈ max(leg), reclaiming ~150ms).
- **OI4 → B** (process-local coverage cache, 600s refresh, `HYBRID_SEARCH_COVERAGE_REFRESH_SECONDS=600`). `A` = per-request SELECT rejected (5–15ms overhead erodes OI3's parallelization gain); `C` = DQ-metric reuse rejected (new infra outside this slice).
- **OI5 → A** (log-only `degraded` observability; no envelope field). `B` = envelope `degraded: bool` rejected (breaks D12 "zero FE churn"; operational telemetry and product-UX exposure are separable surfaces — if UX exposure is ever needed, it goes to a health endpoint, not into `/search`'s response shape).
- **OI6 → B** (`integer()` matcher on `vector_rank` + provider state stamps deterministic embeddings on fixture rows `999060..062`). `A` = literal-null retention rejected (would freeze PR #17 D9's forward-compat slot as "forever null" in the contract, exactly the outcome the slot was designed to avoid). Implementation cost: one UPDATE per fixture row — PR #19a already provides the write path primitives.

### 2.2 Deferred (out of scope, future PRs)

- Cross-encoder / LLM reranker (Phase 4)
- Spellcheck / pg_trgm fuzzy dial
- Multi-entity search
- `/search` as a standalone page with deep-linkable URL state
- Query embedding of filter facets (date range as vector, etc.)
- Embeddings for `incidents` / `codenames` / `actors` surfaces

### 2.3 D13 backfill scheduling — dependency clarification (locked 2026-04-22)

"Prod-like DB" in D13 is *not* a synonym for "production DB". **No production DB exists as of 2026-04-22** (`docker compose ps` + design doc §7.5 confirm; see memory `feedback_verify_prod_dsn_reference.md`). The 95% coverage precondition applies to whichever DB will host end-user traffic when this PR goes live — the current smoke DB is insufficient (PR #20's 2026-04-22 dry-run returned `scanned=0` because it has no seeded reports).

Operational sequencing (locked — all steps outside this PR's git diff):

1. Stand up a prod-like DB with the seeded corpus — out of scope of PR #19b.
2. Run `python -m worker.bootstrap backfill-embeddings` against that DB to achieve coverage > 95%.
3. Verify coverage via the psql query recorded in `docs/plans/pr19a-embedding-backfill.md` (`COUNT(*) FILTER (WHERE embedding IS NOT NULL) / COUNT(*) FROM reports`).
4. Then merge this PR so `/search` traffic hits a DB with real vector coverage — otherwise D5(b) trips permanently and the hybrid path is effectively dead code in production (a quality issue, not a correctness one; CI stays green regardless).

**CI is independent of all four steps.** `services/api/tests/integration/test_pact_state_fixtures.py` seeds deterministic 1536-dim stub vectors onto the pinned fixture rows per OI6 = B. Test green does not depend on backfill state in any DB.

This footnote exists so that anyone reading D13 later — especially operators scanning the plan for release checklists — does not mistake "merge scheduling requires a backfill run with coverage > 95% on whatever prod-like DB hosts end users" as "a prod DB exists; find it and run backfill". It doesn't. Step 1 is a prerequisite, not an implicit state.

---

## 3. Scope

### 3.0 Amendment note — 2026-04-22 (post plan-lock, pre-Group-A)

During Group A pre-kickoff verification, `services/api/src/api/embedding_client.py` was discovered to already exist. PR #19a Group B (merged 2026-04-20) shipped a full api-side `LlmProxyEmbeddingClient` with the identical error taxonomy (`TransientEmbeddingError` / `PermanentEmbeddingError`) that this plan (locked 2026-04-22) assumed had to be newly authored. The `search_embedder.py` new-module bullet reserved in PR #17 §2.2 item 2 was premised on that module not existing in api-service.

**Amendment (locked 2026-04-22):**

1. **`search_embedder.py` is dropped.** Group B's `search_service.py` imports `LlmProxyEmbeddingClient` from `api.embedding_client` directly. No wrapper module, no per-service duplication-within-a-service.
2. **Group A redefined as config-only** (see §4). ~50–150 LOC target (was ~400–500).
3. **Error-taxonomy test coverage inherited** from pre-existing `services/api/tests/unit/test_embedding_client.py` (PR #19a Group B). No new embedder test module.
4. **Config additions shrink from 6 to 3**: `LLM_PROXY_URL`, `LLM_PROXY_INTERNAL_TOKEN`, `LLM_PROXY_EMBEDDING_TIMEOUT_SECONDS` already exist at `services/api/src/api/config.py:98-100` (PR #19a). Only the 3 hybrid-search knobs are net-new.

Rationale memory: `pattern_scope_expansion_before_criteria_lock.md` explicitly warns "grep ALL production paths before declaring criteria." This amendment is the corrective when that check was missed at plan-lock time. D1 / D3 / D4 / D5 / D7 / D9 / all 6 OIs remain untouched — only the physical scope shrinks.

### In scope — BE (api service)

- `services/api/src/api/read/search_fusion.py` *(NEW)* — Pure function `rrf_fuse(fts_hits: list[Hit], vector_hits: list[Hit], k: int = 60) -> list[FusedHit]`. No IO, no logging, no side effects. Heavily unit-testable.
- `services/api/src/api/read/search_service.py` *(MODIFY)* — Add vector path + fusion + degraded-mode branching. Preserve PR #17 cache semantics. D5 trigger logic lives here. **Imports `LlmProxyEmbeddingClient` from `api.embedding_client` directly** (PR #19a Group B artifact — see §3.0 amendment); no new embedder module indirection.
- `services/api/src/api/read/search_cache.py` *(UNCHANGED)* — cache key still `(q_lower, date_from, date_to, limit)`. Hybrid responses reuse the existing cache; degraded responses are cacheable too (same 60s TTL).
- `services/api/src/api/config.py` *(MODIFY)* — add **3 net-new hybrid-search settings**: `HYBRID_SEARCH_COVERAGE_THRESHOLD=0.5`, `HYBRID_SEARCH_VECTOR_K=50` (OI1), `HYBRID_SEARCH_COVERAGE_REFRESH_SECONDS=600` (OI4). Bounds: threshold ∈ `[0.0, 1.0]`, vector_k ≥ 1, refresh_seconds ≥ 1 — enforced via pydantic `field_validator` per the PR #19a `rate_limit_storage_url` precedent. The 3 llm-proxy settings (`LLM_PROXY_URL` / `LLM_PROXY_INTERNAL_TOKEN` / `LLM_PROXY_EMBEDDING_TIMEOUT_SECONDS`) already exist at `config.py:98-100` from PR #19a Group B and are reused as-is — no config drift.
- `services/api/src/api/routers/pact_states.py` *(MODIFY)* — `_ensure_search_populated_fixture` additionally stamps deterministic stub 1536-dim embeddings onto the 3 populated fixture rows (`999060..062`) per OI6 = B. Constants unchanged.

### In scope — tests

- `services/api/tests/unit/test_config.py` *(NEW)* — minimal config validation: 3 new hybrid-search settings have the locked defaults (0.5 / 50 / 600), env-var override parses correctly, out-of-bounds values rejected by the `field_validator` guards (threshold > 1.0, vector_k < 1, refresh_seconds < 1). ~60–100 LOC.
- **Embedder error-taxonomy tests: NOT re-authored.** Coverage inherited from pre-existing `services/api/tests/unit/test_embedding_client.py` (PR #19a Group B). Any future change to error semantics updates that file; Group B's `test_search_service.py` extensions mock `LlmProxyEmbeddingClient` at the seam rather than re-exercising its internals.
- `services/api/tests/unit/test_search_fusion.py` *(NEW)* — RRF correctness (both-hit / FTS-only / vector-only / both-empty), k=60 default, stable tie-break by id DESC, property-based invariant `len(output) == |set(fts_ids) ∪ set(vector_ids)|`.
- `services/api/tests/unit/test_search_service.py` *(EXTEND)* — hybrid path unit tests with a mocked `LlmProxyEmbeddingClient` injected at the call site + mocked vector SQL; 4-branch pin per §9 C4 (happy-hybrid / degraded-transient / degraded-coverage / permanent-500); `vector_rank` slot semantics (OI2 result); cache-hit preserves envelope shape; log line carries new fields.
- `services/api/tests/integration/test_search_route.py` *(EXTEND)* — sqlite integration tests skip the vector leg (dialect guard, same pattern as PR #19a worker); PG-gated tests exercise real hybrid.
- `services/api/tests/integration/test_pact_state_fixtures.py` *(EXTEND)* — verify the populated fixture rows carry `embedding IS NOT NULL` after the provider state runs (OI6 = B).

### In scope — FE

- **Zero FE source changes.**
- `apps/frontend/src/lib/api/__tests__/search-schema.test.ts` *(NEW, small regression test)* — parses `vector_rank: 7` and `vector_rank: null` to pin forward-compat explicitly.

### In scope — contract

- Pact interaction count **15 → 15** (no adds). Populated interaction body gets `integer()` matcher on `vector_rank` per OI6 = B.
- `contracts/openapi/openapi.json` — regenerated; response example for populated path updates `vector_rank: null` → `vector_rank: 7`.

### Out of scope

- `services/worker` changes (PR #19a is upstream).
- `services/llm-proxy` changes (PR #18 already provides the endpoint).
- FE component / palette / hook source changes (D12).
- `staging` / `incidents` / `codenames` embeddings or their retrieval.
- New routes — `/search` is the only touched route.

---

## 4. Groups (locked 2026-04-22 — post §3.0 amendment)

| Group | Scope | Target size |
|:---:|:---|:---:|
| **Plan lock** | ✅ Locked 2026-04-22 (1-round discuss-phase + §3.0 amendment); this document | — |
| **A (config)** | `config.py` — 3 net-new hybrid-search settings (`HYBRID_SEARCH_COVERAGE_THRESHOLD=0.5` / `HYBRID_SEARCH_VECTOR_K=50` / `HYBRID_SEARCH_COVERAGE_REFRESH_SECONDS=600`) with bounds validators + `test_config.py` minimal unit tests. **No new module.** `LlmProxyEmbeddingClient` reused from `api.embedding_client` (PR #19a Group B) — introduced at call site in Group B. | ~50–150 LOC |
| **B (fusion + service wiring)** | `search_fusion.py` (pure) + `search_service.py` hybrid-path branching with `asyncio.gather(fts, embedding)` per OI3 = B + fusion unit tests (including property-based invariant) + extended `test_search_service.py` coverage. Imports `LlmProxyEmbeddingClient` directly from `api.embedding_client`. | ~600–800 LOC |
| **C (degraded mode + integration)** | D5 trigger (request-scope transient + process-scope coverage cache with 600s refresh per OI4 = B) + D9 taxonomy + integration tests pinning the **4-branch** (happy-hybrid / degraded-transient / degraded-coverage / permanent-500). Mirrors PR #19a §9 C4 pattern. | ~500–700 LOC |
| **D (contract + FE regression)** | Pact provider state extension (OI6 = B stub-embedding stamp) + FE schema regression test + pact regeneration + openapi.json regeneration | ~300–400 LOC |
| **Push/PR** | CI 11/11 × 2 green; Codex R1 CLEAN target (maintain PR #14/#15/#17/#18/#19a streak); merge as merge commit (NOT squash) | — |

Ordering rationale:

- A lands config plumbing first so Group B's `search_service.py` wiring reads env values directly — no further config churn mid-group, no back-and-forth between config and service code during review.
- B lands fusion as an isolated pure module before entangling with service branching — unit tests carry highest signal when the target is side-effect free. `search_service.py` imports `LlmProxyEmbeddingClient` from `api.embedding_client` directly at this point; no embedder wrapper module.
- C wires degraded mode with in-commit assertions pinning all 4 branches — matches the PR #19a Group B C4 precedent that produced three consecutive Codex R1 CLEAN rounds.
- D finalizes contract / pact / FE regression. No Group E — FE has no source changes.

Total PR target: ~1450–2150 LOC (down from ~1800–2400 LOC pre-amendment).

---

## 5. Testing strategy

### 5.1 Unit (BE)

- **D3 fusion correctness** — RRF k=60 across both-hit / FTS-only / vector-only / both-empty inputs; property-based invariant on output length; stable tie-break by id DESC.
- **D4 `vector_rank` semantics** — 1-indexed when present; `null` when FTS-only; coverage regression test pinning the OI2 decision.
- **D5 degraded triggers** — two triggers exercised independently + composition; process-scope cache respects 600s refresh interval (OI4 = B).
- **D8 log line** — every new field emitted; `q` text never leaks; `degraded_reason` matches the trigger.
- **D9 error taxonomy** — 422 / 429 / 502 / 503 / 504 / timeout / dimensions-mismatch / malformed-2xx each pinned **at the `search_service.py` seam** (mocked `LlmProxyEmbeddingClient` raises the appropriate exception; assertion is on the service's branch selection, not on the client's parsing). Client-internal coverage already lives in the pre-existing `test_embedding_client.py` and is not duplicated here.

### 5.2 Integration (BE)

- **Happy hybrid on PG** — seeded reports with distinct FTS density + deterministic embeddings; RRF top-N verified end-to-end; `vector_rank` int populated; envelope shape unchanged.
- **Degraded transient** — mocked embedder raises `TransientEmbeddingError`; response 200; all `vector_rank == null`; log has `degraded_reason = "transient"`.
- **Degraded coverage** — coverage cache forced below threshold; embedder spy asserts zero calls; response 200; all `vector_rank == null`; log has `degraded_reason = "coverage"`.
- **Permanent 500** — embedder raises `PermanentEmbeddingError`; response HTTP 500 with short `{detail}`; ERROR-level log.
- **sqlite dialect guard** — sqlite integration tests skip the vector leg entirely (same shape as PR #19a worker guard).

### 5.3 Contract

- Populated: `vector_rank` = `integer()` matcher per OI6 = B; provider state stamps deterministic stub embeddings on fixture rows.
- Empty: unchanged.
- 422: unchanged.
- Provider-state idempotency test + constant-drift test (PR #15 Group C pattern carries).

### 5.4 FE

- Forward-compat parse test — Zod schema accepts both `vector_rank: null` and `vector_rank: 7`.
- No component / hook / palette tests added (no source changes warrant them).

### 5.5 E2E

- Existing Playwright `/search` spec: no change expected (envelope shape unchanged).

---

## 6. Risks & non-risks

### Risks

- **Latency widening on cold embedding cache.** llm-proxy cache-hit is fast; cold miss can push p95 over 500ms. OI3 = B (parallel FTS + embedding) is the primary mitigation.
- **Coverage staleness.** Process-scope coverage cache (OI4 = B) can misclassify for up to 10 minutes after a bulk backfill. Acceptable — coverage moves slowly, and the failure mode is "degraded when hybrid was possible", never the reverse.
- **Pact fixture embedding drift.** If provider-state stub vectors drift from what the vector SQL expects (e.g. dimension change upstream), contract tests will silently de-cover the vector path. Mitigation: `dimensions == 1536` assertion in the embedder + integration test that asserts the fixture row has `embedding IS NOT NULL` post-state.
- **RRF bias toward FTS on tiny corpora.** With `limit=10` and `vector_k=50`, FTS rank-1 almost always wins regardless of vector quality. Acceptable for MVP; cross-encoder rerank is the Phase 4 lever.

### Non-risks (explicit)

- **Envelope re-shape.** PR #17 D9 slot absorbs this change. Zero FE / Pact shape changes.
- **`reports.embedding` schema.** Column exists from PR #14; PR #19a writes to it; this PR only reads.
- **llm-proxy availability coupling.** D9 taxonomy + D5(a) degraded trigger mean `/search` never hard-fails on llm-proxy transient, and `/search` availability is never coupled to llm-proxy availability.
- **Worker / ingest path.** Untouched — this PR is read-side only.
- **sqlite tests.** Dialect guard skips the vector leg — no pgvector-in-sqlite hacks.

---

## 7. Success criteria

- [ ] `/api/v1/search` populated response carries `vector_rank: int` for hits in the vector-kNN top-N
- [ ] `/api/v1/search` degraded response carries `vector_rank: null` everywhere + `degraded=true` log field
- [ ] 4-branch pin per §9 C4 (happy-hybrid / degraded-transient / degraded-coverage / permanent-500) all locked with in-commit integration assertions
- [ ] RRF fusion is a pure function with property-based invariants green
- [ ] Zero FE source changes; schema regression test green across null + int `vector_rank`
- [ ] Pact interaction count unchanged (15); shape preserved; one matcher value change per OI6
- [ ] OpenAPI snapshot delta minimal (example-value only; no new paths)
- [ ] Log line additively extended; existing D16 aggregators keep parsing
- [ ] CI 11/11 × 2 green; Codex R1 CLEAN target
- [ ] Merge as merge commit (NOT squash)
- [ ] PR #17 §2.2 items 2–5 marked closed in `followup_todos` memory
- [ ] Memory hygiene: `pitfall_llm_proxy_no_embedding.md` deleted (per its own "If this is ever fixed, delete this memory" instruction); `pattern_fts_first_hybrid_mvp.md` updated (slot now populated, not just reserved)

---

## 8. References

- `docs/plans/pr17-search-hybrid.md` §2.2 — source roadmap for items 2–5 (this PR closes them)
- `docs/plans/pr18-llm-proxy-embedding.md` — embedding endpoint contract + D7 taxonomy
- `docs/plans/pr19a-embedding-backfill.md` — embedding writer pattern + §9 pre-landing criteria precedent (C4 four-branch pin)
- `services/api/src/api/embedding_client.py` — **primary code dependency.** PR #19a Group B api-side `LlmProxyEmbeddingClient` + error taxonomy. Group B's `search_service.py` imports directly from this module (§3.0 amendment). No new embedding client introduced by this PR.
- `services/api/tests/unit/test_embedding_client.py` — error-taxonomy coverage inherited as-is; not duplicated in this PR.
- `services/api/src/api/read/search_service.py` — PR #17 baseline, to be extended in Group B
- `services/api/src/api/read/search_cache.py` — cache key contract, unchanged
- `services/api/src/api/schemas/read.py` — `SearchHit` / `SearchResponse` DTOs (unchanged)
- `services/api/src/api/embedding_writer.py` — PR #19a api-side writer (architecture precedent informing `search_service.py` layering; not a code dep for this PR)
- `services/api/src/api/config.py:98-100` — existing llm-proxy settings (reused as-is; Group A adds only hybrid-search knobs)
- `services/llm-proxy/src/llm_proxy/routers/embedding.py` — `POST /api/v1/embedding` (ultimate call target, reached via `api.embedding_client`)
- `services/llm-proxy/src/llm_proxy/main.py:97` — embedding router mount (confirms OI5 blocker resolved)
- `services/worker/src/worker/bootstrap/embedding_client.py` — worker-side sibling of `api.embedding_client`; historical precedent only. This PR does not import from worker.
- `services/worker/src/worker/bootstrap/embedding_writer.py` — PR #19a worker writer (historical precedent)
- Memory `pattern_fts_first_hybrid_mvp.md` — slot-reservation rationale
- Memory `pattern_enrichment_tx_boundary_catch.md` — transient-caught-inside / permanent-propagates pattern
- Memory `pattern_service_local_duplication_over_shared.md` — why not a shared embedder package
- Memory `pattern_log_schema_allowlist.md` — no-raw-text log posture
- Memory `pattern_d10_empty_as_first_class_state.md` — empty-state render contract (FE, unchanged)
- Memory `pattern_pact_literal_pinned_paths.md` — pact path/query-string literal pattern
- Memory `pitfall_sqlalchemy_regconfig_literal.md` — FTS parameterized query caveat (carried from PR #17)
- `DPRK_Cyber_Threat_Dashboard_설계서_v2.0.md:580` — `/search` endpoint spec (hybrid)
- `DPRK_Cyber_Threat_Dashboard_설계서_v2.0.md:601` — 500ms p95 SLO (restored here)

---

## 9. Group C — pre-landing review criteria (LOCKED 2026-04-22)

Declared **before** implementation. Replicates PR #19a §9 pattern: each criterion becomes an in-commit test assertion inside the Group C commit. The "4-branch pin" (C4) is the structural analogue to PR #19a C4 and is the precedent that produced three consecutive Codex R1 CLEAN rounds.

### 9.1 Architectural choices (locked)

- **Scope = hybrid read path only.** No writes, no worker touch, no llm-proxy touch.
- **Embedding client = reuse existing `api.embedding_client`** (service-local per `pattern_service_local_duplication_over_shared.md`; PR #19a Group B already shipped it, so this PR introduces no new embedding client — see §3.0 amendment). Group B's `search_service.py` imports `LlmProxyEmbeddingClient` directly at the call site.
- **Degraded trigger = 2-source OR** (request-scope transient OR process-scope coverage cache). Not 3-source, not 1-source.

### 9.2 Criteria (pinned as in-commit test assertions)

- **C1 — Envelope shape invariant.** Pact populated / empty / 422 responses keep field sets identical to PR #17. Only `vector_rank` value flips. Pinned by a contract-shape regression test in `services/api/tests/integration` asserting the JSON key set is exactly what PR #17 locked.

- **C2 — Fusion purity.** `rrf_fuse()` has no IO, no logging, no side effects, and is deterministic across repeated calls with the same inputs. Pinned by a purity test that calls twice and compares outputs + a module-import inspection test asserting zero module-level side effects.

- **C3 — Dialect guard.** sqlite route calls skip the vector leg entirely. Pinned by a sqlite-backed integration test that spies on the vector SQL executor and asserts zero calls.

- **C4 — Four-branch pin (mirror of PR #19a C4).** Four in-commit integration tests, one per branch. Each branch has its own test function (not a parametrize) so failure signals localize cleanly:
  - **Happy hybrid**: embedder returns 200 + 1536-dim vector → vector kNN hits → RRF fusion → response 200 with `vector_rank: int` where kNN-present.
  - **Degraded transient**: embedder raises `TransientEmbeddingError` → response 200, all `vector_rank: null`, log `degraded=true, degraded_reason="transient"`.
  - **Degraded coverage**: coverage cache forced below threshold → embedder never invoked (spy assertion), response 200, all `vector_rank: null`, log `degraded=true, degraded_reason="coverage"`.
  - **Permanent 500**: embedder raises `PermanentEmbeddingError` → response HTTP 500 with short `{detail}`, ERROR-level log.

### 9.3 Out of scope for Group C

- Pact / contract changes (Group D).
- FE regression test (Group D).
- OpenAPI regeneration (Group D).
- Any worker-side or llm-proxy-side change.

---

## 10. Group A kickoff — proposal (config-only, post-amendment)

All blockers upstream of Group A are cleared as of 2026-04-22:

- `main` at `e93555b` (PR #20 merged, worker suite 929/1).
- PR #18 `POST /api/v1/embedding` mounted (`services/llm-proxy/src/llm_proxy/main.py:97`) and operational.
- PR #19a `api.embedding_client` shipped — no new embedding client needed (§3.0 amendment).
- OI1–OI6 locked (§2.1, B/A/B/B/A/B).
- §3.0 scope amendment locked (search_embedder.py dropped; Group A is config-only).
- §9 pre-landing criteria locked.
- D13 scheduling dependency documented (§2.3) — not a CI/correctness blocker.

**Group A scope recap (~50–150 LOC):**

- `services/api/src/api/config.py` *(MODIFY)* — 3 net-new `Settings` fields:
  - `hybrid_search_coverage_threshold: float = 0.5` — bounds `[0.0, 1.0]` via `@field_validator`
  - `hybrid_search_vector_k: int = 50` — bounds `>= 1` via `@field_validator`
  - `hybrid_search_coverage_refresh_seconds: int = 600` — bounds `>= 1` via `@field_validator`
- `services/api/tests/unit/test_config.py` *(NEW)* — ~6 minimal unit cases:
  1. Defaults match plan (0.5 / 50 / 600).
  2. Env override parses (`HYBRID_SEARCH_VECTOR_K=25` yields `25`).
  3. `HYBRID_SEARCH_COVERAGE_THRESHOLD=1.5` rejected.
  4. `HYBRID_SEARCH_COVERAGE_THRESHOLD=-0.1` rejected.
  5. `HYBRID_SEARCH_VECTOR_K=0` rejected.
  6. `HYBRID_SEARCH_COVERAGE_REFRESH_SECONDS=0` rejected.

**Verification gate to close Group A:**

- [ ] `services/api` suite stays green (no regression from the new validators on the existing fields).
- [ ] `test_config.py`'s 6 cases green.
- [ ] No changes to `services/api/src/api/embedding_client.py` (read-only dep).
- [ ] No new modules under `services/api/src/api/read/` (search_fusion.py / search_service.py modifications belong to Group B).
- [ ] Atomic commit message: `feat(api): add hybrid-search config knobs (PR #19b Group A)`.

**Open question before Group A starts:** none — OIs locked, §3.0 amendment accepted, scope minimal. Proceed.

**Branch plan:** `feat/pr19b-hybrid-search` off `main @ e93555b` — covers Groups A / B / C / D as a single PR (PR #19a precedent: one feature branch, multi-group commits). Group A lands as the first commit on that branch. No push until Group A's `test_config.py` is green locally. Group B starts only after Group A's commit is clean.

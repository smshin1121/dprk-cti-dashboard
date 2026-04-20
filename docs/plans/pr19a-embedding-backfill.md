# PR #19a — embed-on-ingest + reports.embedding backfill

**Status:** Locked v1 (plan lock: 2026-04-20). Next: Group A. Additive infra/data PR that must merge before PR #19b hybrid `/search`. No FE changes. No `/api/v1/search` contract changes.

**Base:** `main` at `b99597f` (PR #18 llm-proxy embedding endpoint merged 2026-04-20).

**Why this PR exists:** PR #17 deliberately shipped `/api/v1/search` as FTS-only MVP and reserved `SearchHit.vector_rank: int | null` for a later additive upgrade. PR #18 now provides `POST /api/v1/embedding`, but **current `reports.embedding` coverage is effectively 0%**: worker code defines the schema column only and writes no vectors. If PR #19b hybrid search shipped first, its D8 degraded-mode would fire on nearly every query and hybrid would be "wired but usually inactive". PR #19a fixes that by making embedding population part of the report write path and by backfilling existing `reports` rows whose `embedding IS NULL`.

**Execution order lock:** PR #19a merges first -> one-shot backfill runs on `main` -> PR #19b hybrid `/search` starts with real vector coverage.

---

## 0. Lock summary (pinned invariants)

Three lines that survive any implementation debate and belong in the plan doc so Group A can't drift from them:

1. **Embed text:** `title + "\n\n" + summary` when summary is non-null and not whitespace-only; otherwise `title` alone. Never send whitespace to llm-proxy (422 per PR #18 D7 input validator).
2. **Backfill pacing:** default `--sleep-seconds 2` between batches (natural ~30 req/min ceiling against PR #18's locked bucket) **+** always honor llm-proxy `Retry-After` header on actual 429. Two mechanisms compose — proactive pacing prevents most 429s, reactive adaptive handles spikes.
3. **Embedding write shape:** `embedding` UPDATE is **post-insert, PostgreSQL-only, skipped on sqlite**. `upsert_report()` INSERTs the report row first (dialect-agnostic, sqlite-safe). Caller then chains `embed_client.embed(text)` → `sa.text("UPDATE reports SET embedding = :vec WHERE id = :id")` guarded by `engine.dialect.name == "postgresql"`. `tables.py` stays pgvector-free.

OI locks (§2.1): OI1=A (with whitespace refinement), OI2=A, OI3=A, OI4=B (sleep=2 + Retry-After), OI5=A.

D3/D9 refined (see §2): INSERT commits before llm-proxy is contacted — two-transaction boundary makes fail-open behavior fall out naturally.

---

## 1. Goal

Populate `reports.embedding` reliably enough that PR #19b can treat vector retrieval as a real signal path, not a mostly-empty fallback.

1. **Ingest path**: every newly inserted report attempts an llm-proxy embedding call before the report row is written.
2. **Backfill path**: a one-shot CLI fills `reports.embedding` for existing rows where the column is still `NULL`.
3. **Error semantics**: llm-proxy `502/503/504/429` fail open for the write path (`embedding` stays `NULL`, row still lands, retry later); llm-proxy `422` is a caller/protocol bug and must fail loud.
4. **Idempotency**: both promote-path and backfill guard on `embedding IS NULL`; repeated runs must not rewrite already-populated vectors.
5. **Scope control**: only `reports.embedding` is touched. `staging.embedding`, `/similar`, incidents, and actor-derived embeddings remain out of scope.

### Explicit non-goals

- Hybrid `/search` query path, pgvector kNN, or RRF fusion (PR #19b)
- Any `/api/v1/search` request or response contract change
- FE palette or Zod changes
- `staging.embedding` writes
- `incidents` or `codenames` embeddings
- Automatic background retry queue / scheduler
- Real OpenAI smoke in CI
- New standalone CI job (worker tests extend existing coverage)

---

## 2. Decisions — proposed for lock

| ID | Item | Proposed | Rationale |
|:---:|:---|:---|:---|
| **D1** | Target column | `reports.embedding` only | This is the column PR #19b will query. Anything else is accidental scope growth. |
| **D2** | Text to embed | `title + "\n\n" + summary` when summary exists, otherwise `title` | Matches the search corpus better than title-only while staying deterministic and cheap. |
| **D3** | Write timing | **Refined (locked):** `upsert_report()` INSERTs the report without touching `embedding` (sqlite-safe, `tables.py` unchanged). After INSERT commits, caller chains `embed_client.embed(text)` → PG-only `sa.text("UPDATE reports SET embedding = :vec WHERE id = :id")` guarded by `engine.dialect.name == "postgresql"`. On sqlite the UPDATE is skipped. | Keeps `tables.py` pgvector-free, preserves sqlite unit-test portability, makes the fail-open boundary explicit (INSERT durable before HTTP call). Trade-off is one extra round-trip on the happy path; cost (~5ms DML) is noise against embed latency (~200-500ms). |
| **D4** | Worker adapter module | `services/worker/src/worker/bootstrap/embedding_client.py` | Keeps llm-proxy coupling out of `upsert.py` and gives backfill + promote path one shared adapter. |
| **D5** | llm-proxy error taxonomy | `502/503/504/429` -> skip write, keep `NULL`, retry later. `422` -> propagate as worker error. | Locked from discuss-phase. Fail-open for transient/provider pressure; fail-loud for caller bug or protocol drift. |
| **D6** | Batch size | Backfill sends batches of up to `16` texts | Matches PR #18 max batch and avoids adapter-level fragmentation. |
| **D7** | Rate-limit posture | Backfill honors llm-proxy `30/minute` bucket; no local override | PR #18 rate limit is load-bearing. Backfill must adapt to it, not bypass it. |
| **D8** | Idempotency rule | Only rows with `embedding IS NULL` are candidates. Existing non-null vectors are never recomputed in this PR. | Makes re-runs safe and bounded. |
| **D9** | Degrade semantics on ingest | **Refined (locked):** Two-transaction boundary. INSERT commits *before* llm-proxy is contacted. llm-proxy `502/503/504/429` → skip the PG-only UPDATE, row stays with `embedding=NULL`. `422` propagates as a worker error on the embed step (INSERT is already durable — loud failure is on the embed/UPDATE phase, not on ingest). | Decouples ingest availability from llm-proxy availability while preserving loud-fail on caller-bug / protocol drift. |
| **D10** | Backfill ordering | Oldest-first by `published ASC, id ASC` | Deterministic progress, easier restart reasoning, and stable test assertions. |
| **D11** | CLI surface | New argparse subcommand under `worker.bootstrap`: `backfill-embeddings` | Reuses the existing bootstrap DB/session/audit shape instead of inventing a new service entrypoint. |
| **D12** | Logging | Worker logs counts and ids only; no raw title/summary text in logs | Carries forward PR #18 no-raw-text posture into the caller layer. |
| **D13** | Test transport | Promote-path and backfill tests use `httpx.MockTransport` / fake adapter, not live llm-proxy | CI must stay offline and deterministic. |
| **D14** | CI wiring | Extend existing `worker-tests` job; no new job | Scope is worker-only and fits existing CI signal split. |

### 2.1 Open items — LOCKED 2026-04-20

- **OI1**: embed text shape — **LOCKED A** (with whitespace refinement)
  - `A` title + summary when summary is non-null and not whitespace-only; otherwise `title` alone
  - `B` title only
  - *Rationale:* matches PR #17 FTS corpus (`0001_initial_schema.py:101` indexes `coalesce(title,'') || ' ' || coalesce(summary,'')`) — same corpus for both signals keeps hybrid meaningful. Whitespace-only guard avoids llm-proxy 422 per PR #18 D7 input validator.
- **OI2**: promote-path failure on `429` — **LOCKED A**
  - `A` fail-open with `NULL`
  - `B` hard-fail the row
  - *Rationale:* ingestion resilience over per-row embedding coverage. The 30/min bucket can saturate during news spikes; coupling ingest availability to that would be wrong. DQ layer can surface NULL-coverage% later.
- **OI3**: backfill CLI location — **LOCKED A**
  - `A` `worker.bootstrap.cli`
  - `B` separate `worker.embedding.cli`
  - *Rationale:* reuses existing DB/session/audit/`--dry-run` scaffolding. Split to its own module only when embedding scope expands beyond `reports`.
- **OI4**: backfill throttle expression — **LOCKED B (with refinement)**
  - `A` rely on llm-proxy 429 + bounded batch only
  - `B` add worker-side sleep/throttle guard as well
  - *Lock detail:* default `--sleep-seconds 2` between batches (natural ~30 req/min ceiling against PR #18's locked bucket) **+** always honor llm-proxy `Retry-After` header on actual 429. Two mechanisms compose — proactive pacing prevents most 429s; reactive adaptive handles spikes.
- **OI5**: one-shot backfill resumability — **LOCKED A**
  - `A` implicit via `embedding IS NULL`
  - `B` explicit checkpoint file/state
  - *Rationale:* DB is authoritative; checkpoint file adds distributed state with desync risk and no offsetting benefit.

---

## 3. Scope

### In scope — worker

- `services/worker/src/worker/bootstrap/embedding_client.py` *(NEW)*
  - Thin llm-proxy client using `httpx.AsyncClient`
  - Request DTO mirror for `POST /api/v1/embedding`
  - Maps llm-proxy `429/502/503/504/422` into worker-local exceptions / result enum
  - Sends `X-Internal-Token`
  - Validates returned `dimensions == 1536`
  - Never logs raw text

- `services/worker/src/worker/bootstrap/config.py` or existing worker config module *(NEW or extended)*
  - `LLM_PROXY_URL`
  - `LLM_PROXY_INTERNAL_TOKEN`
  - timeout
  - optional worker-side backfill throttle knobs if OI4 = B

- `services/worker/src/worker/bootstrap/upsert.py` *(MODIFY)*
  - `upsert_report(...)` gains an optional embedding client dependency
  - Fresh insert path attempts embed before `INSERT`
  - Existing-row paths do **not** backfill in-place in this PR; only fresh inserts and dedicated CLI write vectors
  - `422` propagates
  - `429/502/503/504` leave `embedding=NULL`

- `services/worker/src/worker/bootstrap/cli.py` *(MODIFY)*
  - New `backfill-embeddings` subcommand
  - Args:
    - `--database-url`
    - `--batch-size` default 16, max 16
    - `--limit` optional total rows cap
    - `--dry-run`
    - `--sleep-seconds` if OI4 = B
  - Queries `reports WHERE embedding IS NULL`
  - Builds embed text from D2
  - Writes vectors in bounded batches
  - Emits summary counts: scanned / attempted / embedded / skipped_transient / failed_422

- `services/worker/src/worker/bootstrap/tables.py` *(maybe modify for production-only column access helper, not sqlite metadata column)*
  - Keep sqlite test metadata portable; do not force pgvector into sqlite-local table definitions
  - If needed, use SQLAlchemy table reflection or textual update in PG-only paths

### In scope — tests

- `services/worker/tests/unit/test_embedding_client.py` *(NEW)*
  - happy path
  - `dimensions != 1536` fail-loud
  - `422` -> propagate classification
  - `429/502/503/504` -> transient classification
  - token header wired
  - no raw text in logs

- `services/worker/tests/integration/test_upsert_embedding.py` *(NEW)*
  - inserted report with successful embed writes non-null vector
  - `429/502/503/504` leaves row inserted with `embedding=NULL`
  - `422` aborts the operation
  - idempotent rerun of same report does not rewrite vector

- `services/worker/tests/integration/test_backfill_embeddings_cli.py` *(NEW)*
  - selects only `embedding IS NULL`
  - bounded batch behavior
  - idempotent rerun embeds 0 additional rows
  - mixed transient failures leave subset `NULL` and report correct counts
  - `--dry-run` writes nothing
  - if OI4 = B, throttle path is exercised without wall-clock sleep abuse

- Existing `worker-tests` suite extensions
  - ensure pre-existing worker tests keep passing

### Out of scope

- `services/api` code changes
- `/api/v1/search` changes
- Pact changes
- FE changes
- staging table embeddings
- Similar reports backfill or quality audit metrics for embeddings

---

## 4. Groups

| Group | Scope |
|:---:|:---|
| **Plan lock** | Freeze this document after discuss-phase |
| **A** | llm-proxy worker client + config/token wiring + error taxonomy + unit tests |
| **B** | Promote-path integration in `upsert_report` + integration tests proving insert/skip/fail-loud behavior |
| **C** | One-shot `backfill-embeddings` CLI + idempotency / dry-run / bounded-batch tests |
| **D** | CI wiring in existing `worker-tests` job + coverage/command updates if needed |
| **Push/PR** | Standard CI + Codex review + merge |

Ordering rationale:
- A defines the adapter and taxonomy used by both B and C.
- B proves new writes are covered.
- C covers existing rows.
- D only after tests are final.

---

## 5. Testing strategy

### 5.1 Unit

- `embedding_client` maps llm-proxy responses exactly:
  - `200` -> vectors + dimensions 1536
  - `429/502/503/504` -> transient/fail-open classification
  - `422` -> hard failure classification
- no raw title/summary text appears in log output
- token and timeout are passed to `httpx.AsyncClient`

### 5.2 Integration

- New report insert with mock embedding succeeds and persists vector
- Same insert with transient llm-proxy failure still persists report row with `embedding=NULL`
- `422` prevents silent bad writes
- Existing report rerun remains idempotent

### 5.3 CLI

- `backfill-embeddings` only selects `NULL` rows
- batch size never exceeds 16
- repeated run on same DB is a no-op
- transient failures can be resumed later because rows remain `NULL`
- dry-run emits counts without DB mutation

### 5.4 CI

- No new job
- `worker-tests` includes new unit + integration + CLI coverage
- Offline only; no real llm-proxy or OpenAI calls

---

## 6. Risks

- **SQLite vs pgvector schema gap**
  - worker-local sqlite metadata intentionally omits pgvector columns
  - PR implementation must avoid breaking existing sqlite-memory tests
  - likely mitigation: PG-aware update path or reflected table access only where needed

- **Backfill pressure on llm-proxy**
  - PR #18 caps at `30/minute`
  - worker-side pacing should prevent a 429 storm if OI4 = B locks

- **Caller/llm-proxy contract drift**
  - dimensions mismatch or 422 must fail loud
  - this is why `422 -> 500/worker failure` is locked

- **Text source quality**
  - title+summary gives better retrieval signal, but missing summaries mean mixed input richness
  - acceptable for this slice; hybrid search can still degrade on sparse vectors later if needed

---

## 7. Success criteria

- [ ] New report inserts can populate `reports.embedding`
- [ ] Transient llm-proxy failures do not block report ingestion
- [ ] llm-proxy `422` fails loud and is covered by tests
- [ ] Backfill CLI populates existing `NULL` rows in bounded batches
- [ ] Re-running backfill is idempotent
- [ ] Existing worker test surface remains green
- [ ] CI passes with no new job and no live network dependency
- [ ] PR #19b can assume non-trivial `reports.embedding` coverage after backfill completes

---

## 8. References

- `docs/plans/pr17-search-hybrid.md` §2.2 — hybrid search roadmap
- `docs/plans/pr18-llm-proxy-embedding.md` — llm-proxy endpoint contract and D7 taxonomy
- `services/worker/src/worker/bootstrap/upsert.py` — current report insert path
- `services/worker/src/worker/bootstrap/cli.py` — existing argparse / DB session pattern
- `services/worker/src/worker/bootstrap/tables.py` — sqlite-local schema caveat (no pgvector column)

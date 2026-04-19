# PR #18 — llm-proxy embedding endpoint (infra)

**Status:** 🔒 **Locked 2026-04-20** — Draft v2 after 1-round discuss-phase. D1–D8 frozen; OI1–OI8 resolved A/A/A/B/**A**/A/A/C (OI5 flipped from Draft v1's proposed-B to A: rate limit IS included this PR — cost-surface abuse/runaway guard is load-bearing even on an internal endpoint). Four reviewer refinements incorporated into D2 / D3 / D6 / D7 / D8. This is the infra prerequisite for the hybrid `/search` follow-up per PR #17 plan §2.2. Intentionally small-scope: one new endpoint on `services/llm-proxy` + provider adapter + cache + rate limit + tests. No dprk-cti-api or FE changes this PR.

**Surface posture:** internal endpoint only — never part of the public API. All access flows through `services/api` which owns the `LLM_PROXY_INTERNAL_TOKEN` value. Direct caller access from outside the private network is structurally blocked by the X-Internal-Token middleware (fail-closed 401/503).

**Base:** `main` at `d633b3e` (PR #17 FTS-only `/search` merged 2026-04-20).

**Mapping to design doc v2.0 §7/§9:**
- §7.7 LLM 프록시 경계: the proxy holds provider API keys; callers never see them. PR #18 extends the proxy surface by one endpoint — boundary stays intact.
- §9.x 보안 게이트: inbound `X-Internal-Token` shared-secret (already enforced by `main.py::require_internal_token`). PR #18 adds no new auth surface.
- §14 phase map: this is an infra PR sandwiched between PR #17 (FTS-only search) and PR #19+ (hybrid search follow-up). Not listed as a numbered phase; tracked via PR #17 plan §2.2 follow-up roadmap.

**Current llm-proxy state (evidence pin):**
- `services/llm-proxy/src/llm_proxy/main.py` — FastAPI app with X-Internal-Token middleware (fail-closed at 503 if env var empty, 401 on mismatch); only `/healthz` + mounted `provider` router.
- `services/llm-proxy/src/llm_proxy/routers/provider.py` — ONE route: `GET /api/v1/provider/meta` returning static dict. 12 lines.
- `services/llm-proxy/src/llm_proxy/telemetry.py` — OTel hook (no-op if `OTEL_EXPORTER_OTLP_ENDPOINT` unset).
- `services/llm-proxy/pyproject.toml` — deps: `fastapi / httpx / pydantic-settings / uvicorn / otel-*`. No `redis`, no `slowapi`, no `openai`.
- **No tests directory.** PR #18 introduces the first test suite for this service.

---

## 1. Goal

Ship a minimal, well-tested `POST /api/v1/embedding` on `services/llm-proxy` that the hybrid `/search` follow-up PR can consume for query-time embedding generation. Keep the scope tight: one endpoint, one real provider (OpenAI), one mock provider for CI, Redis cache, pydantic-settings-based config, full-test coverage. No feature code in `services/api` this PR — the consumer wiring lands in PR #19+.

1. **Endpoint**: `POST /api/v1/embedding` — accepts 1..N texts, returns per-text 1536-dim embedding vectors matching `reports.embedding vector(1536)` (migration 0001).
2. **Provider**: OpenAI first (`text-embedding-3-small` default). Mock provider for CI so the pipeline does not require an API key.
3. **Cache**: Redis-backed per-text cache keyed on `sha256(model + "\n" + text)`. Long TTL (24h) since embeddings are deterministic for a given model+text.
4. **Observability**: response includes `model` + `provider` + `usage.prompt_tokens` + `latency_ms` + `cache_hit`. Structured log `embedding.generate` mirrors.
5. **First-ever llm-proxy test suite**: unit tests for cache + provider adapter + config; integration tests for route (auth guard + error taxonomy + mock provider end-to-end).

### Explicit non-goals (deferred)

- Chat / completion / LLM inference endpoints
- Consumer wiring in `services/api` (`search_embedder.py` reserved name, NOT created this PR)
- Variable-dimension output (`text-embedding-3-small`'s dim-truncation feature) — always 1536 this PR
- Cross-provider A/B comparison
- Token counting pre-flight utility
- Pact producer wiring for llm-proxy (OI4 — proxy is internal-only; dprk-cti-api is still the only Pact provider in this repo)
- Redis-backed rate-limit per X-Internal-Token principal (OI5)
- Observability redaction of text content (logs `n_texts` not raw texts — baked into D8, not deferred)
- Embedding backfill CLI for existing `reports` rows (separate worker PR under Phase 3 slice 4+)

---

## 2. Decisions — LOCKED 2026-04-20

| ID | Item | Locked | Rationale |
|:---:|:---|:---|:---|
| **D1** | Endpoint shape | **`POST /api/v1/embedding`** (mounted at `main.py` via `app.include_router(embedding.router, prefix="/api/v1/embedding", tags=["embedding"])`). POST because request body may carry multiple texts and text content is not URL-encode-friendly for non-trivial inputs. | Mirrors OpenAI's own `POST /v1/embeddings` API shape; FastAPI treats POST + JSON body as canonical for this kind of workload. |
| **D2** | Request / Response DTO | **Request**: `{texts: list[str], model?: str}` — `texts` length 1..16, each text non-empty + non-whitespace-only, no null. `model` optional; server default = env-configured. **Response**: `{provider: str, model: str, dimensions: int, items: [{embedding: list[float], index: int}], usage: {prompt_tokens: int, total_tokens: int}, latency_ms: int, cache_hit: bool}`. The top-level **`dimensions` field is new in Draft v2** — while the value is always `1536` this PR (D4 of PR #17 pinned by `reports.embedding vector(1536)`), exposing it explicitly lets downstream assertions (`search_embedder` Zod schema, backfill workers, monitoring) pin the expected dim without hardcoding. Variable-dim support is OI7=A deferred, but the field is reserved so callers don't have to parse `items[0].embedding.length` to get it. `index` mirrors the request `texts[index]` ordering so a batch partially served from cache still maps back correctly. `cache_hit` is overall (true ⇔ every item served from cache). | Mirrors the envelope pattern used in `/search` (D9): typed per-item body + top-level `latency_ms` + cache bit. `usage` field comes from OpenAI's response verbatim and gives callers a cheap cost signal. The `dimensions` field makes downstream contract testing cheap: Zod `z.literal(1536)` or similar, regression-guards a future OI7 flip before any caller is broken. |
| **D3** | Provider selection + env contract | **`pydantic-settings`-based `Settings` class.** Env vars: `LLM_PROXY_EMBEDDING_PROVIDER` ∈ {`openai`, `mock`} (no default — explicit set required); `LLM_PROXY_EMBEDDING_MODEL` default `text-embedding-3-small`; `OPENAI_API_KEY` required when provider=`openai`; `LLM_PROXY_EMBEDDING_TIMEOUT_SECONDS` default `10`; `LLM_PROXY_EMBEDDING_MAX_BATCH` default `16`. **Startup fail-closed**: if provider=`openai` and `OPENAI_API_KEY` is empty, the app refuses to boot. **Mock provider dev/test-only lock (Draft v2 refinement)**: if `LLM_PROXY_EMBEDDING_PROVIDER=mock` AND `APP_ENV=prod`, the app ALSO refuses to boot — a config validator checks `(provider, app_env)` together so a production misconfiguration cannot silently serve deterministic-fake vectors into real workloads. Dev / test / CI freely use `mock`; prod MUST specify `openai`. | `pydantic-settings` is already on the dep list but unused; this PR starts using it properly. Making provider explicit (no default) forces deployment configs to pick a lane. The mock+prod lock is critical: deterministic 1536-dim vectors derived from `sha256(text)` would INGEST cleanly into `reports.embedding` and silently corrupt hybrid ranking for every cached row — a failure mode worse than a hard 503, since it produces plausible-but-wrong retrieval results. Fail-closed at startup is the mitigation. |
| **D4** | Auth | **Reuse existing `X-Internal-Token` middleware** (`main.py::require_internal_token`). No new auth layer. Calling service (dprk-cti-api) holds `LLM_PROXY_INTERNAL_TOKEN` in its own env. | Proxy is internal-network-only behind the shared secret already. A second layer for one endpoint would be gratuitous complexity. |
| **D5** | Rate limit (OI5=A, Draft v2) | **slowapi-based `30/minute` per X-Internal-Token principal** applied at the route level via `@_limiter.limit("30/minute")`. Key function hashes the token (`sha256(token).hexdigest()[:16]`) so the token value never reaches Redis keys / logs. Shared Redis storage with D6 cache (single `REDIS_URL` env var). Custom 429 handler emits `{error: "rate_limit_exceeded", message: "30 per 1 minute", retry_after_seconds: int}` with `Retry-After` header — same shape as `services/api`'s slowapi-based rate limit (lifted pattern). Rate limit fires AFTER the X-Internal-Token middleware so 401/503 requests do NOT consume the bucket. With `max_batch=16`, this caps texts throughput at **480 texts/minute per caller** — comfortable for query-time palette usage + room for moderate backfill; pushed higher if hybrid search load data shows contention. | Conservative initial setting per reviewer: `embedding` is a cost-surface endpoint, and a runaway caller (bug loop, retry storm, misconfigured backfill) could burn thousands of OpenAI dollars before anyone notices. 30/min gives ~3x headroom over expected palette usage (~10 unique queries/min per active analyst at peak) without throttling legitimate work. Bumping to 60/min later is additive — one-line change. Pinning the rate limit on the (token) principal not on the IP matches our "internal, not public" posture and gives per-caller bucket granularity once multiple services start using the proxy. |
| **D6** | Cache key + TTL | **Key**: `embedding:{sha256(provider + "\n" + model + "\n" + text)}` (per-text, NOT per-request — batch with partial cache hit works). The **`provider` segment is new in Draft v2**: without it, switching `LLM_PROXY_EMBEDDING_PROVIDER` from `openai` to a hypothetical future second provider that happens to use the same model-name convention (`text-embedding-3-small` is a convention; other providers could mint conflicting names) would collide on cache keys and serve cross-provider semantic vectors. Including `provider` makes the cache space provider-partitioned by construction. Empty-string or whitespace-only text is rejected at DTO level before cache lookup (OI1 batch with one bad text → whole request 422, no partial cache write). **TTL**: 24h. Empty responses are NOT cached (422 before cache layer). **Storage**: Redis (`redis>=5` added to pyproject). Graceful degrade on `RedisError` (log + compute). **Dev/test mode**: pytest fixture provides in-memory fake redis (same pattern as dprk-cti-api's `fake_redis` fixture). | Embeddings are deterministic for a given `(provider, model, text)` tuple; long TTL dramatically reduces cost for repeat queries. `provider + model + text` fully identifies the semantic vector space; any change to any of the three opens a fresh cache slot. |
| **D7** | Timeout + error taxonomy | **Per-request timeout default 10s** (env-configurable via `LLM_PROXY_EMBEDDING_TIMEOUT_SECONDS`). **httpx AsyncClient** with explicit `timeout=httpx.Timeout(total_seconds)`. **Error mapping (Draft v2 — split upstream 5xx from local timeout)**: upstream returned 5xx → **502 Bad Gateway** with `{detail: "upstream error", upstream_status: int, retryable: true}` body; local httpx timeout (client-side deadline hit, upstream never responded) → **504 Gateway Timeout** with `{detail: "upstream timeout", timeout_seconds: int, retryable: true}` body — distinct status AND body shape so caller retry logic can differentiate "server failed to respond" from "server too slow"; upstream 429 → **429** bubble with `{detail: "upstream rate limit", upstream_status: 429, retryable: true, retry_after_seconds?: int}` (populated from upstream `Retry-After` header if present); invalid request (empty texts list, empty string in texts, batch > max_batch, whitespace-only text) → **422**; missing API key for configured provider → **503** at startup (cannot serve — app boot fails). **No automatic retry inside the proxy** — callers own retry policy. Graceful RedisError → log + serve from upstream (never 5xx on cache miss). | Callers (dprk-cti-api `search_embedder`) need explicit error bodies to decide whether to retry or fall back to FTS-only. Pushing retry inside the proxy couples the proxy to a specific caller's retry budget; keeping it caller-side keeps the proxy thin. The 502-vs-504 split is load-bearing: a caller seeing 504 repeatedly should extend its client-side timeout or shed load upstream of this call; a caller seeing 502 should consider provider-side outage handling. Conflating them costs observability. |
| **D8** | Model + version observability | **Response fields**: `provider` + `model` + `dimensions` in every response (D2). The response-level `model` is **what the upstream actually returned** (OpenAI sometimes returns a more specific version than the requested string); the request-level model comes from `req.model` or `settings.default_model`. **Structured log** (one line per request): `{event: "embedding.generate", provider, model_requested, model_returned, n_texts, total_text_chars: int, cache_hits_count, cache_misses_count, upstream_latency_ms?: int, total_latency_ms, redis_ok: bool, rate_limited: bool, error?: str}`. **LOCKED: raw text content is NEVER logged.** Counts only (`n_texts`, `total_text_chars`, cache-hit/miss counts, batch size). A reviewer auditing llm-proxy logs must be unable to reconstruct any user input from them. This is enforced by (a) the log schema has no `texts` / `text` / `input` field; (b) an integration test emits a request with an identifiable sentinel string and asserts the sentinel does NOT appear anywhere in captured log output (same pattern as PR #17 `search.query` `q_len` PII guard). **OTel span attributes** mirror the log fields — same LOCKED "no raw text" posture. | OpenAI periodically updates model internals under the same string name; the response's `model` field sometimes carries a more specific version suffix. Logging BOTH `model_requested` AND `model_returned` lets a future cache-invalidation script target specific upstream drift without touching caller code. The no-raw-text lock is hard security: embeddings can inadvertently reveal input content via reconstruction attacks, but logs are the more immediate leak surface. Making it a test-enforced invariant means a careless future edit that adds `payload=req.texts` to a log line breaks CI, not production. |

### 2.1 Open Items — RESOLVED (1-round discuss-phase 2026-04-20)

- **OI1 → A** — Batch support from day one: `texts: list[str]`, length 1..16. Max-batch enforced at DTO + `LLM_PROXY_EMBEDDING_MAX_BATCH=16` env override. OpenAI's API is batch-native so zero adapter cost; backfill workers will consume it.
- **OI2 → A** — Redis cache included. Hybrid `/search` follow-up's p95 ≤ 250ms budget structurally requires most embedding calls be cache hits; deferring cache would make that SLO harder to hit in PR #19+.
- **OI3 → A** — Deterministic mock provider included: `sha256(text)` seed produces a stable 1536-dim vector per text. Same text always yields same vector (regression-testable). CI runs offline. Prod-mode guard locked at D3 prevents mock from serving production traffic.
- **OI4 → B** — Pact wiring for llm-proxy deferred. dprk-cti-api remains the sole pact producer in the repo; PR #18 stays scope-tight.
- **OI5 → A (FLIPPED from Draft v1 proposed-B)** — Rate limit IS included. Reviewer flagged that `X-Internal-Token` alone does not guard against runaway callers, bug loops, or retry storms — embedding is a **cost-surface endpoint** and needs a ceiling from day one. Also: the hybrid `/search` follow-up needs backend-pressure observability in place before it ships, not as a subsequent retrofit. **Locked at `30/minute` per X-Internal-Token principal** — conservative initial value, bump to 60/min is a one-line additive change if the cap bites legitimate traffic.
- **OI6 → A** — OpenAI + mock only. `EmbeddingProvider` protocol means second-provider integration later is a direct extension.
- **OI7 → A** — Fixed 1536 dim. Matches `reports.embedding vector(1536)` from migration 0001. The `dimensions` response field (D2) surfaces the value explicitly for Zod / downstream assertions without hardcoding; if OI7 later flips to B, the field's type can widen without breaking consumers that pinned the value.
- **OI8 → C** — Model string pass-through at the request + `model_returned` logged from upstream. No hard version pin, but observability captures actual drift for forensic cache-flush decisions later.

---

## 3. Scope

### In scope — BE (services/llm-proxy)

- `services/llm-proxy/src/llm_proxy/config.py` *(NEW)* — `Settings(BaseSettings)` class loading env vars listed in D3. Field validators enforce: `provider` ∈ {`openai`, `mock`}; `timeout_seconds > 0`; `max_batch ∈ [1, 100]`. Root validator: provider=`openai` ⇒ `OPENAI_API_KEY` non-empty, AND provider=`mock` ⇒ `APP_ENV != "prod"` (D3 Draft v2 refinement — blocks prod-mock misconfiguration at startup). Also reads `REDIS_URL` shared between D6 cache AND D5 slowapi storage. Lazy singleton via `@lru_cache def get_settings()`.
- `services/llm-proxy/src/llm_proxy/providers/base.py` *(NEW)* — `EmbeddingProvider(Protocol)` with one async method `embed(texts: list[str], model: str) -> ProviderResult`. `ProviderResult` dataclass: `vectors: list[list[float]]`, `model_returned: str` (what provider actually responded with — D8), `prompt_tokens: int`, `total_tokens: int`, `upstream_latency_ms: int`.
- `services/llm-proxy/src/llm_proxy/providers/openai.py` *(NEW)* — `OpenAIEmbeddingProvider` using `httpx.AsyncClient` to `POST https://api.openai.com/v1/embeddings`. Headers: `Authorization: Bearer {OPENAI_API_KEY}`. Maps upstream 5xx → `UpstreamError(status=5xx)`, local `httpx.TimeoutException` → `UpstreamTimeoutError`, upstream 429 → `UpstreamRateLimitError` (carries upstream `Retry-After` if present). Does NOT retry inside the provider (D7).
- `services/llm-proxy/src/llm_proxy/providers/mock.py` *(NEW)* — `MockEmbeddingProvider` returning deterministic 1536-dim vectors derived from `sha256(text)` + small float encoding. `prompt_tokens = sum(len(t) // 4 for t in texts)` (approximation). `model_returned = f"mock/{requested_model}"` so logs show the mock origin unambiguously (D8 observability).
- `services/llm-proxy/src/llm_proxy/cache.py` *(NEW)* — Redis-backed cache with async `get_many(keys)` + `set_many({key: vector}, ttl_seconds)`. Graceful `RedisError` → log + empty result (caller computes + sets later). Pure `cache_key(*, provider: str, model: str, text: str) -> str` — **D6 Draft v2 refinement: provider segment included** so `openai`-vs-future-second-provider cannot collide. Blank text raises at the function boundary (router-bypass defense).
- `services/llm-proxy/src/llm_proxy/rate_limit.py` *(NEW)* — **D5 Draft v2 refinement**. `slowapi.Limiter` factory using Redis storage (`REDIS_URL` shared with D6 cache — single Redis connection, two logical keyspaces). Key function: `lambda req: sha256(req.headers.get('X-Internal-Token', 'anonymous')).hexdigest()[:16]` — hashes the token so the raw secret never touches slowapi storage / logs. Custom 429 exception handler registered on the app emits the locked body shape (D7). Rate limit fires AFTER the X-Internal-Token middleware (slowapi runs at route-decorator time, middleware runs earlier in the chain, so unauthed 401/503 requests never consume the bucket).
- `services/llm-proxy/src/llm_proxy/routers/embedding.py` *(NEW)* — `POST /api/v1/embedding` route with `@_limiter.limit("30/minute")` decorator, request model, response model, cache lookup (per-text), provider dispatch for cache misses, envelope assembly (includes `dimensions: int` per D2), structured log emit (raw-text-never-logged invariant).
- `services/llm-proxy/src/llm_proxy/main.py` — +3 lines: `app.include_router(embedding.router, prefix="/api/v1/embedding", tags=["embedding"])`, `app.state.limiter = rate_limit.get_limiter()`, `app.add_exception_handler(RateLimitExceeded, rate_limit.rate_limit_exceeded_handler)`. Nothing else changes.
- `services/llm-proxy/src/llm_proxy/errors.py` *(NEW)* — `UpstreamError`, `UpstreamTimeoutError`, `UpstreamRateLimitError`, `ConfigurationError`, `InvalidInputError` exception classes + central `@app.exception_handler` mapping each to HTTP status + body shape per D7. The upstream-5xx vs local-timeout split carries the distinct handlers (502 vs 504, distinct body shapes).
- `services/llm-proxy/pyproject.toml` — add `redis>=5`, `slowapi>=0.1.9`, `openai>=1.50` (or use raw httpx if we stay close to the REST surface — Group B decides, but dep is pre-approved here).

### In scope — tests (first-ever llm-proxy test suite)

- `services/llm-proxy/tests/__init__.py` + `conftest.py` *(NEW)* — pytest infra, fake-redis fixture (lifted pattern from `services/api/tests/conftest.py`), `mock_provider` fixture, `openai_provider_httpx_mock` fixture using `httpx.MockTransport`, `limiter_reset` autouse fixture (clears slowapi buckets between tests — same pattern as `services/api`).
- `services/llm-proxy/tests/unit/test_cache.py` *(NEW)* — cache key stability across 6 input variations (same provider+model+text → same key; different provider same model → different key; different model same provider → different key; same inputs different order in batch → keys identical per-text); **D6 Draft v2 cross-provider collision guard** (asserts `cache_key(provider="openai", model="m", text="t")` ≠ `cache_key(provider="mock", model="m", text="t")`); TTL wiring; graceful RedisError degrade; empty-text raises (defense against router bypass).
- `services/llm-proxy/tests/unit/test_openai_provider.py` *(NEW)* — httpx MockTransport: happy-path response parsing + `model_returned` populated from upstream, 5xx → `UpstreamError(status=5xx)`, 429 → `UpstreamRateLimitError` with retry_after from `Retry-After` header, local timeout → `UpstreamTimeoutError` with timeout_seconds set, missing/empty API key preflight.
- `services/llm-proxy/tests/unit/test_mock_provider.py` *(NEW)* — deterministic output (same text in → same vector out across invocations), distinct texts give distinct vectors, 1536-dim pin, `model_returned` prefixed with `mock/` per D8, prompt_tokens > 0 on non-empty text.
- `services/llm-proxy/tests/unit/test_config.py` *(NEW)* — env var parsing; provider validator (`openai` / `mock` only); fail-closed on provider=openai + missing key; **D3 Draft v2 mock-in-prod lock** (`APP_ENV=prod + provider=mock` raises at Settings init); `timeout_seconds > 0` and `max_batch ∈ [1, 100]` validators.
- `services/llm-proxy/tests/unit/test_rate_limit.py` *(NEW)* — **D5 Draft v2**. Key-func returns stable SHA-256 prefix for the same X-Internal-Token, distinct prefixes for distinct tokens, `"anonymous"` fallback for no-header case. Raw token value NEVER appears in the computed key (regression guard pinning the hash-before-storage invariant).
- `services/llm-proxy/tests/integration/test_embedding_route.py` *(NEW)* — `TestClient(app)` end-to-end covering the full spec:
  - Auth guard: 401 no token, 503 when env `LLM_PROXY_INTERNAL_TOKEN` empty.
  - Happy path (mock provider): single text + batch (2..16 texts), 200 envelope with all D2 fields including `dimensions: 1536`.
  - 422 branches: empty `texts` list / empty string in `texts` / whitespace-only string / batch > 16 / text field null.
  - 502 on upstream 5xx (OpenAI provider with httpx-mock injecting 503 response).
  - 504 on local timeout (httpx-mock injecting `TimeoutException`) — **distinct from 502** per D7 split.
  - 429 bubble from upstream (httpx-mock injects 429 with `Retry-After: 30`).
  - **D5 Draft v2 rate-limit test**: drain the `30/minute` bucket, 31st request → 429 with locked `{error: "rate_limit_exceeded", message: "30 per 1 minute", retry_after_seconds}` body + `Retry-After` header. Second caller with distinct X-Internal-Token (simulated) gets a distinct bucket — draining caller A leaves caller B's budget intact.
  - **D8 LOCKED raw-text PII guard**: request carries identifiable sentinel string `"SENTINEL-PII-CANARY-7F3A"` in `texts[0]`. Captured log output (via `caplog`) asserted to NEVER contain that substring — failure would indicate a regression re-introducing raw-text logging. Also asserts `event="embedding.generate"`, `n_texts`, `total_text_chars`, `cache_hits_count`, `cache_misses_count`, `model_requested`, `model_returned`, `provider`, `total_latency_ms` all present on the log record.
  - **Cache round-trip**: fresh Redis → request → populate → second request with same texts → `cache_hit=true`, zero upstream calls.
  - **Partial-cache-hit batch**: batch `[t1, t2, t3]` where t1+t2 are pre-seeded in cache — response has all 3 vectors, upstream called with only `[t3]`, `cache_hit=false` overall (since not all hit) but per-text cache-hit counts logged correctly.
  - OpenAPI shape pin: request/response schemas + error response refs appear at `/openapi.json` (dev mode).

### Out of scope (does NOT ship this PR — reserved names)

- `services/api/src/api/read/search_embedder.py` — consumer adapter. Reserved name; NOT created.
- `services/api/src/api/read/search_service.py` — does NOT gain a hybrid path this PR.
- `contracts/pacts/api-llm_proxy.json` — OI4 = B means no pact producer wiring for llm-proxy.
- Embedding backfill CLI for existing `reports` rows.

---

## 4. Groups (proposed)

| Group | Scope |
|:---:|:---|
| Plan lock | `docs/plans/pr18-llm-proxy-embedding.md` Draft v2 Locked (this commit) |
| A | `config.py` (with D3 prod-mock guard) + `errors.py` (split upstream 5xx vs timeout vs rate-limit) + `cache.py` (with D6 provider-in-key) + `providers/base.py` + `providers/mock.py` + `rate_limit.py` + unit tests for each. Redis/slowapi deps added to pyproject |
| B | `providers/openai.py` with httpx-mock unit tests (5xx / timeout / 429 / happy); `model_returned` observability pin from D8 |
| C | `routers/embedding.py` + `main.py` mount + request/response DTOs (incl. D2 `dimensions` field) + structured log (D8 no-raw-text invariant) + exception handlers (D7 four status shapes) |
| D | Integration tests `tests/integration/test_embedding_route.py` — full spec coverage from §5 below including D5 rate-limit drain + D8 PII sentinel + 502/504 split + partial-cache-hit batch |
| E | CI wiring — extend existing `python-services (llm-proxy)` matrix job or add a new `llm-proxy-tests` job with Redis service + env vars; `pytest services/llm-proxy/tests -q` as CI step |
| Push + PR + CI + Codex + merge | Standard flow — `gh pr create --body-file docs/plans/pr18-body.md`, CI 11/11 × 2, Codex R1 target CLEAN (4th consecutive), `gh pr merge --merge --delete-branch` |

Ordering rationale: config + cache + mock + rate-limit first (all offline, no network), then real OpenAI provider (mocked via httpx), then route (depends on all of A+B), then integration (depends on route), then CI. No cross-group backward dependencies.

---

## 5. Testing strategy

- **Unit** (target ~90% coverage of new code): every new module has a dedicated test file. Cache, config, and providers tested in isolation with no route layer.
- **Integration**: `fastapi.testclient.TestClient(app)` hits `POST /api/v1/embedding` with mock provider + fake-redis. Covers auth guard, input validation, upstream error surfaces, cache round-trip, OpenAPI shape.
- **Contract**: OI4 = B means no pact wiring this PR. If OI4 flips to A, add `test_pact_producer.py` in Group E following `services/api`'s pattern exactly.
- **Manual smoke (post-merge, optional)**: one-off script `scripts/smoke_embedding.py` hitting a real OpenAI key for 3 sample texts, verifying 1536-dim output + reasonable token counts. Not a CI gate.

**Test runner**: `uv run --project services/llm-proxy --all-groups pytest services/llm-proxy/tests -q` (Windows: same env-export idiom as `services/api`).

---

## 6. Risk & non-risk notes

- **Risk: OpenAI provider ships a breaking API change**. Mitigation: adapter isolates the upstream call; breakage surfaces as `UpstreamError` with a clear 502 body. No-code-change-required fix path: update the adapter's request/response shape in one file.
- **Risk: cache staleness after model-or-provider drift**. Mitigation: cache key includes BOTH `provider` AND `model` (D6 Draft v2). A bump from `-3-small` to `-3-large`, or a switch from `openai` to a future second provider, opens a fresh cache slot automatically — zero risk of cross-provider semantic-vector collision. Stale entries age out via 24h TTL. If a within-same-model-name drift surfaces, D8's `model_returned` log field captures the drift for a forensic flush.
- **Risk: 30/min rate limit (D5 / OI5 = A) bites legitimate traffic during hybrid-search follow-up launch**. Mitigation: the value is conservative ON PURPOSE for infra-PR scope — a flip to 60/min is a one-line `@_limiter.limit("60/minute")` edit + snapshot regen if the cap proves too tight under real load. The structured log's `rate_limited: bool` field + slowapi's built-in 429 counter let ops observe how often the cap fires before touching code.
- **Risk: deterministic-mock provider accidentally serves production traffic**. Mitigation: D3 Draft v2 `APP_ENV=prod + provider=mock` startup guard — the app refuses to boot in that configuration. Fail-closed pattern consistent with `LLM_PROXY_INTERNAL_TOKEN` guard. Without this lock, deterministic fake vectors would ingest cleanly into `reports.embedding` and silently corrupt hybrid retrieval (harder failure mode than a hard 503).
- **Risk: raw text content leaks into logs / traces**. Mitigation: D8 LOCKED no-raw-text invariant enforced by test. Integration test emits a sentinel canary and asserts it does NOT appear in captured log output. Any future edit that adds `payload=req.texts` or similar to a log call breaks CI, not production.
- **Non-risk: fail-closed startup behavior**. If `OPENAI_API_KEY` is missing when provider=`openai`, OR provider=`mock` when `APP_ENV=prod`, the service refuses to boot. Misconfigured pods die at startup rather than silently serving 503s (OPENAI case) or silently serving deterministic fakes (mock-prod case) for every request.
- **Non-risk: `services/api` unchanged**. This PR cannot cause search/similar/dashboard regressions because it adds zero code to the consuming service.

---

## 7. Success criteria

1. `POST /api/v1/embedding` serves happy path via mock provider with NO env setup beyond `LLM_PROXY_INTERNAL_TOKEN` + `LLM_PROXY_EMBEDDING_PROVIDER=mock` (CI default).
2. Same endpoint serves happy path via OpenAI provider when `OPENAI_API_KEY` + `LLM_PROXY_EMBEDDING_PROVIDER=openai` are set (manual smoke — out of CI).
3. Every error case in D7 round-trips to the correct HTTP status + body shape including the **502-vs-504 split** (upstream 5xx vs local timeout). Regression-guarded by integration tests.
4. **D5 rate limit verified end-to-end**: draining the 30/min bucket returns 429 with the locked body shape + `Retry-After` header; distinct X-Internal-Token principals get distinct buckets.
5. Redis cache round-trip proven: miss → populate → hit, with partial-batch-hit correctness AND **D6 Draft v2 provider-in-key cross-collision guard**.
6. **D8 LOCKED no-raw-text invariant holds**: sentinel-canary integration test passes — a specific string in request payload must NOT appear anywhere in captured log output. All other D8 observability fields (`provider`, `model_requested`, `model_returned`, `n_texts`, `total_text_chars`, `cache_hits_count`, `cache_misses_count`, `total_latency_ms`, `rate_limited`) present on every request's log record.
7. **D3 Draft v2 prod-mock guard**: attempting to start the service with `APP_ENV=prod + LLM_PROXY_EMBEDDING_PROVIDER=mock` raises at Settings init, fail-closed.
8. Response envelope includes `dimensions: 1536` (D2 Draft v2 refinement); downstream callers can pin the value in Zod without hardcoding.
9. `services/llm-proxy/.venv/Scripts/python.exe -m pytest services/llm-proxy/tests -q` passes 100% locally + in CI.
10. Existing `services/llm-proxy` behavior unchanged — `/healthz`, `/api/v1/provider/meta`, X-Internal-Token guard all still green.
11. OpenAPI shape at `/openapi.json` (dev only) cleanly shows the new endpoint with request/response schema + all error response refs (422 / 429 / 502 / 504 / 503).

---

## 8. References

- Plan: `docs/plans/pr17-search-hybrid.md` §2.2 — the 5-item follow-up roadmap that motivates this PR
- Current llm-proxy: `services/llm-proxy/src/llm_proxy/main.py` (middleware + router mount pattern), `routers/provider.py` (existing 12-line router template)
- Embedding dim: `services/api/migrations/` 0001 — `ALTER TABLE reports ADD COLUMN embedding vector(1536)` (pins 1536-dim requirement)
- Existing `fake_redis` fixture: `services/api/tests/conftest.py` (pattern to lift for llm-proxy tests)
- Existing X-Internal-Token middleware: `services/llm-proxy/src/llm_proxy/main.py:36-63`
- OpenAI embeddings API docs: `POST https://api.openai.com/v1/embeddings` (request: `{input: string | list[string], model: string, dimensions?: int, encoding_format?: 'float' | 'base64'}` / response: `{object: 'list', data: [{object: 'embedding', embedding: list[float], index: int}], model: str, usage: {prompt_tokens: int, total_tokens: int}}`)
- Memory references: `pitfall_llm_proxy_no_embedding` (the blocker this PR closes), `pattern_fts_first_hybrid_mvp` (the forward-compat strategy this PR's existence validates)

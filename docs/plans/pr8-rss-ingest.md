# PR #8 Plan — Phase 1.3a RSS Ingest Worker → Staging

**Phase:** 1.3a (design doc v2.0 §14 W4 — split: RSS in PR #8, TAXII 2.1 in PR #9).
**Status:** **Locked 2026-04-16.** D1–D11 locked via 2026-04-16 discuss-phase (2 rounds: initial D-decision pass + P1/P2 contradiction resolution). Changes after this point require an explicit scope-change note in the implementing PR description.
**Predecessors:** PR #4 (BigInt PK preflight), PR #5 (ETL normalize + upsert library), PR #6 (ETL CLI), PR #7 (Data Quality Gate + audit row-level + `dq_events` — merged 2026-04-15 as `a1b347e`).
**Successors:** PR #9 (TAXII 2.1 ingest worker — reuses the same `@flow` + CLI + staging writer + audit/dq lineage infra introduced here), Phase 2 read API (review/promote endpoints `POST /reports/review/{id}`), Phase 4 LLM enrichment (staging.summary / staging.embedding fill).

> **§14 W4 split note.** The design doc v2.0 §14 W4 line reads "RSS/TAXII 수집 Worker (Prefect 플로우), Staging → Review 큐". That single roadmap item is split across **PR #8 (RSS only, this plan)** and **PR #9 (TAXII 2.1)**. The split is recorded in `memory/phase_status.md` so future phase audits don't flag W4 as incomplete when PR #8 merges. The Staging → Review queue write side lands in PR #8; the read/promote side lands with Phase 2 core API (§14 W5).

---

## 1. Goal

Deliver a **scheduled-capable RSS ingest worker** that polls a versioned feed list, fetches feed payloads over httpx with ETag/Last-Modified caching, parses them with feedparser, normalizes each entry into a `staging` row, and persists with dedup via `ON CONFLICT (url_canonical) DO NOTHING`. Every run emits run-level + feed-level lineage to `audit_log` and run-level/feed-level pre-ingest quality observations to `dq_events`, binding both to a shared uuid7 `run_id` that interoperates with PR #7's bootstrap + DQ lineage.

**Non-goals (explicit)**:
- **TAXII 2.1** — deferred to PR #9 (D1).
- **Production promotion path** (staging → reports/sources/tags write) — deferred to PR #9 or bundled with Phase 2 read API (D2). PR #8 writes **only** to `staging`.
- **`POST /reports/review/{id}` approve/reject endpoints** — §14 W5 Core API scope, Phase 2.
- **Frontend review UI** — Phase 2.
- **Prefect deployment / schedule / worker infrastructure** — `@flow` decoration + local CLI invocation only (D3). External scheduling (cron / systemd / k8s CronJob) is the operator's responsibility until a dedicated infra PR.
- **Bootstrap upsert-wide `ON CONFLICT` refactor** (`upsert.py` 4 entity tables) — deferred. Race surface is eliminated by D2 (staging-only write), so bootstrap refactor is not a prerequisite (D4). Remains tracked in `followup_todos.md`.
- **LLM enrichment** (`staging.summary`, `staging.tags_jsonb`, `staging.confidence`, `staging.embedding`) — Phase 4. PR #8 writes them as NULL.
- **staging row row-level DQ** (null-rate / value-domain / year-range against staging columns) — out of scope. Only **run-level and feed-level** pre-ingest DQ lands here (D9). PR #7's 11 production-side expectations are not extended.
- **Rate limiting on the admin `POST /ingest/rss/run` endpoint** — remains a followup from P1.1 / PR #7, not PR #8 scope (lands with Phase 2 read API hardening).
- **`sources` table column additions for feed runtime state** — explicitly rejected. Feed runtime state (ETag, Last-Modified, last_fetched_at, consecutive_failures) lives in a **separate `rss_feed_state` table** per D7.
- **Node.js 20 GHA action bump** — cleanup, tracked separately with deadline 2026-06-02.

---

## 2. Locked Decisions (2026-04-16)

| ID | Decision | Rationale |
|:---:|:---|:---|
| **D1** | **Scope = RSS / Atom only**. TAXII 2.1 (`taxii2-client`, async HTTP, collection discovery, §6.2 Tampering HTTPS pinning) deferred to PR #9. §14 W4 is split across two PRs. `phase_status.md` records the split so future audits don't flag W4 incomplete. | `feedparser` + `httpx` is a well-understood sync fetch + parse combo covering the 5 initial vendor feeds documented in §3.4 (Ahnlab, EST, Kaspersky, Mandiant, Recorded Future). TAXII adds auth discovery, collection enumeration, STIX 2.1 bundle parsing, and signature verification (§6.2 Tampering) — doubles the review surface. Split keeps each PR's rollback unit sized to one client library. M1 exit (§14.1) does not require TAXII. |
| **D2** | **Write target = `staging` table only**. The RSS worker is forbidden from touching `sources`, `groups`, `codenames`, `reports`, `tags`, `incidents`, or any production entity. Staging rows land with `status='pending'`, LLM-filled columns NULL, `promoted_report_id` NULL. Production promotion is out of scope entirely (no `python -m worker.promote`, no promote API). | The check-then-insert race in `worker.bootstrap.upsert` (PR #5/#6 known-defer) only matters if a second writer appears on the same production tables. Restricting the RSS worker to the staging table — which already has `UNIQUE(url_canonical)` from migration 0002 — makes the race surface **empty**: there is no concurrent writer on production tables until promote paths land. This **defers the bootstrap `ON CONFLICT` refactor entirely** and keeps PR #8 focused on one concern: "feed → staging." Promotion single-thread assumption remains valid because no promote path exists yet. |
| **D3** | **Prefect scope = `@flow` decoration + local CLI entrypoint**. `services/worker/src/worker/main.py`'s `ingest_sources` stub is renamed to `rss_ingest` and wraps a single callable exposed via `python -m worker.ingest run`. **No Prefect deployment, no schedule, no worker infrastructure.** 15-minute polling is an operator responsibility (cron / systemd / k8s CronJob) until a dedicated infra PR. | Prefect 2.x deployment requires a Prefect server + agent/worker runtime — Phase 1 explicitly defers this class of infrastructure. `@flow` decoration satisfies the §14 W4 "Prefect 플로우" wording at zero infra cost: the flow is callable both as a Python function (for tests) and via CLI (for operators), and later wrapping it with `prefect deploy` is a ~10 LOC additive change. |
| **D4** | **Dedup strategy = `INSERT ... ON CONFLICT (url_canonical) DO NOTHING` on staging only**. On conflict, the RSS worker records the row as `skipped_duplicate` in the per-run counters and emits no error. Bootstrap upsert (`upsert.py` 4 entity tables) is NOT converted to ON CONFLICT in this PR — the known-defer stays deferred because D2 eliminates the concurrency surface that would require it. | Staging has a UNIQUE constraint on `url_canonical` since migration 0002. `DO NOTHING` is the minimal pg-native pattern and needs no savepoint ceremony. `skipped_duplicate` counter is the operational signal that the feed has been polled before (feature, not failure). Bootstrap-wide ON CONFLICT refactor stays tracked in `followup_todos.md` "From PR #5 / PR #6" for the PR that first introduces concurrent production writers. |
| **D5** | **HTTP client = `httpx` (already in `services/worker/pyproject.toml`). Parser = `feedparser` (new dep).** Fetch and parse are decoupled: `httpx.AsyncClient` handles GET with timeout/headers/ETag/Last-Modified/redirect policy, yields `bytes`; `feedparser.parse(content)` takes bytes and yields the parsed document. **`feedparser.parse(url)` (the network-embedded form) is forbidden.** | feedparser's URL-embedded fetch uses urllib with non-configurable timeouts, no header injection, and no mock-transport support. Decoupling fetch from parse gives: (1) httpx MockTransport for integration tests, (2) per-request timeout + User-Agent, (3) standard HTTP retry semantics, (4) the same client shared across async code. feedparser keeps its parser value — it's the most complete RSS/Atom format handler. New dep footprint: feedparser (pure Python, no transitive deps). |
| **D6** | **Feed configuration = `data/dictionaries/feeds.yml`** (new versioned YAML). Initial content: 5 vendor feeds documented in design doc §3.4 (Ahnlab, EST, Kaspersky, Mandiant, Recorded Future). Schema per entry: `slug` (unique), `display_name`, `url`, `kind ∈ {rss, atom}`, `enabled` (bool), `poll_interval_minutes` (advisory — D3 does not schedule, operator uses this). **No `source_id` field** — vendor-to-CTI-source linking is deferred to the review/promote PR or a dedicated source-seeding step. `staging.source_id` is always written as NULL in PR #8. Loader follows `aliases.yml` / `AliasDictionary` pattern from PR #5. YAML bijection lint (unique `slug`, unique `url`). | Same rationale as D8 of PR #7: a committed YAML with bijection lint is diff-reviewable, git-blame-able, and ships with the wheel. DB rows would mix feed runtime state with CTI domain entities and require an admin UI to edit. Env vars don't scale to 5+ feeds with structured metadata. `source_id` excluded because PR #8 writes only to staging (D2) and production `sources` rows may not yet exist for all vendors. Including `source_id` in feeds.yml creates a testing/operational contradiction: Acceptance #4 would need to assert NULL vs non-NULL conditionally, and the promote path that would actually use the FK doesn't exist yet. Vendor linking is a natural part of the promote/review workflow (Phase 2). |
| **D7** | **Feed runtime state = new `rss_feed_state` table via migration 0006**. Schema: `(feed_slug TEXT PK, etag TEXT NULL, last_modified TEXT NULL, last_fetched_at TIMESTAMPTZ NULL, last_status_code INTEGER NULL, last_error TEXT NULL, consecutive_failures INTEGER NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())`. Populated on every fetch. **Columns are NOT added to `sources`** — feed runtime state has different lifecycle and semantics from a CTI source entity. | User-rejected the `sources` column approach: "feed 상태는 CTI source 엔티티와 수명/의미가 다릅니다." A feed can be retired / paused / broken without affecting the `sources` row that represents the vendor's downstream CTI provenance. `feed_slug` PK (not numeric id) so the mapping is visible in logs without a join. `consecutive_failures` enables a simple backoff / disable policy downstream (not implemented in PR #8, only recorded). Migration 0006 is reversible (downgrade drops table). |
| **D8** | **Audit lineage — new `worker.ingest.audit` thin module that writes directly to `audit_log_table`**. PR #7's `worker.bootstrap.audit` is **not extended** — its `write_run_audit` hardcodes `actor=AUDIT_ACTOR` ("bootstrap_etl") and `entity=RUN_ENTITY` ("etl_run"), its `AuditBuffer` validates `entity in ENTITY_TABLES_AUDITED` (which does not include "staging"), and `AuditMeta` requires `workbook_sha256` (RSS has no workbook). Changing those signatures would risk regressions on the 500-test bootstrap suite. Instead, PR #8 introduces `worker.ingest.audit` which: (a) imports shared utilities — `new_uuid7`, `_normalize_for_json`, `audit_log_table` — from `worker.bootstrap.audit`; (b) defines its own frozen `IngestRunMeta(run_id: UUID, feeds_path: str, started_at: datetime)` (no workbook_sha256); (c) provides `write_ingest_run_audit(session, action, meta, detail)` writing `actor="rss_ingest"`, `entity="rss_run"`, `entity_id=NULL`; (d) provides `write_staging_insert_audit(session, meta, staging_id, url_canonical)` writing `actor="rss_ingest"`, `entity="staging"`, `entity_id=str(staging_id)`, `diff_jsonb={"op":"insert","url_canonical":...,"meta":...}`. Action constants: `RSS_RUN_STARTED`, `RSS_RUN_COMPLETED`, `RSS_RUN_FAILED`, `STAGING_INSERT`. Each run emits 1 start + 1 completed-or-failed + N × staging_insert (N = successful inserts). Skipped duplicates emit no audit event. Run events wrapped in savepoints per PR #7 Codex Round 1.1 pattern. `worker.bootstrap.audit` module has **zero modifications** — only its `new_uuid7`, `_normalize_for_json`, and `audit_log_table` re-import are used. | The bootstrap audit module is intentionally bootstrap-specific: `AUDIT_ACTOR`, `RUN_ENTITY`, `ENTITY_TABLES_AUDITED`, `AuditMeta.workbook_sha256` are all ETL-domain concepts. Generalizing them for RSS would either bloat the module with conditional logic or weaken the bootstrap-side validation (`RowAuditEvent.__post_init__` rejects entities not in `ENTITY_TABLES_AUDITED` — removing that check to allow "staging" degrades bootstrap's safety). A thin ingest-specific module with 4 functions + 4 constants + 1 dataclass (~80 LOC) is cheaper and safer than a generic refactor. The shared utilities (`new_uuid7`, `_normalize_for_json`, `audit_log_table`) are the right reuse boundary — they have no bootstrap-specific assumptions. §9.4 Repudiation compliance is maintained because every staging write still lands in `audit_log`. |
| **D9** | **DQ reuse — `dq_events` for pre-ingest, run-level / feed-level metrics only**. No row-level DQ on staging rows. No extension of PR #7's 11 post-load production expectations. All PR #8 expectations are new, prefixed with `feed.*` or `rss.*` to avoid collision with PR #7's `tags.type.enum_conformance` and other production-side checks. Sink fan-out identical to PR #7 (`StdoutSink` + `DbSink` + optional `JsonlSink`) — same `Sink` protocol, no new sink type. | User explicit: "dq_events 재사용도 가능하지만 PR #8에서는 pre-ingest run-level/feed-level DQ로 제한. row-level DQ나 post-load PR #7 expectation registry 확장은 과하지 않게." Run-level/feed-level is the right granularity: a per-row check on a raw feed item is premature (the item hasn't been LLM-enriched yet — Phase 4). Name prefix `feed.*` / `rss.*` enforces the boundary at query time — operators can filter `dq_events WHERE expectation LIKE 'feed.%'` for ingest-side trends without touching production-side state. |
| **D10** | **PR #8 feed-level DQ expectation set = 4 checks, all `warn` severity**. (1) `feed.fetch_failure_rate` — ratio of feeds whose GET returned non-2xx / non-304 / exception in the run, warn at > 0.20. (2) `feed.parse_error_rate` — ratio of fetched feeds whose `feedparser.parse` set `bozo = 1` AND `bozo_exception` is a hard error (not benign warnings), warn at > 0.10. (3) `feed.empty_title_rate` — ratio of parsed entries across all feeds whose `<title>` was empty or whitespace-only, warn at > 0.05. (4) `rss.tags.unknown_rate` — **renamed from `tags.type.unknown_rate`** per user feedback — ratio of raw feed entries whose heuristic pre-classification (using the same `classify_tags` function from `worker.bootstrap.normalize`, against any hashtag tokens in title/summary) yielded `TAG_TYPE_UNKNOWN`, warn at > 0.30 (higher threshold than bootstrap because feed metadata is noisier). Explicitly documented as a "staging enrichment / classifier preview metric," NOT a production quality gate — staging rows don't have a `type` column and the real production check stays as PR #7's `tags.type.enum_conformance`. | Four checks is enough signal to detect the three operational failure modes (fetch infra down / feed format drift / vendor changed title semantics / classifier dictionary drift) without over-engineering. All `warn` because RSS feeds are exogenous: a vendor formatting change should not fail CI. Threshold justification: 0.20 fetch failure is "one of five feeds broken"; 0.10 parse error is conservative; 0.05 empty title assumes any sane vendor keeps this near zero; 0.30 unknown-rate is intentionally loose because raw vendor tags drift faster than the canonical dictionary. All thresholds revisitable after the first real-feed run. |
| **D11** | **Testing strategy — static XML fixtures + `httpx.MockTransport` + sqlite-memory only**. No network I/O in any test. **No real-pg integration test in CI for PR #8.** Fixtures: 3 committed `.xml` files under `services/worker/tests/fixtures/rss/` — one happy RSS 2.0 payload, one happy Atom 1.0 payload, one deliberately broken payload to exercise the parse_error path. `httpx.MockTransport` routes feed URLs → fixture bytes with configurable status codes + ETag/Last-Modified headers. Staging inserts target sqlite-memory via `worker.bootstrap.tables` mirror (same pattern as PR #5/6 unit tests). sqlite-memory covers the `ON CONFLICT DO NOTHING` dedup behaviour (sqlite implements `INSERT ... ON CONFLICT` semantics). Real-pg coverage of `staging UNIQUE(url_canonical)` is deferred to a **post-merge manual smoke** against a docker-compose pg container (same pattern as PR #7's real-workbook smoke deferral). The existing `worker-tests` CI job is extended with the new sqlite-memory test modules; neither `data-quality-tests` nor any new CI job is added. | User explicit: "원격 HTTP 호출 금지, static XML fixtures + httpx.MockTransport가 맞습니다." sqlite-memory is sufficient for dedup/ON CONFLICT semantics and for the audit/DQ assertion suite. A real-pg CI job is not justified in PR #8: the only pg-specific concern is `UNIQUE(url_canonical)` enforcement, which sqlite models faithfully. The `data-quality-tests` real-pg job from PR #7 ran bootstrap + DQ against production pg because 5 expectation families used pg-specific SQL (`EXTRACT`, `CHECK`, `NUMERIC` coercion) — PR #8's DQ expectations are pure Python counter arithmetic with no SQL queries, eliminating the pg-specific motivation. If TAXII in PR #9 introduces pg-specific staging queries (e.g., embedding similarity), that PR should add a real-pg CI job. |

---

## 3. Scope

### In scope

- **Migration** — `db/migrations/versions/0006_rss_feed_state.py` (new). Creates `rss_feed_state` per D7. Reversible.
- **`data/dictionaries/feeds.yml`** — new versioned feed list with 5 initial vendor feeds per D6. Wheel force-include per the `aliases.yml` pattern.
- **`services/worker/src/worker/ingest/`** package (new):
  - `__init__.py`, `__main__.py` (CLI hook `python -m worker.ingest`)
  - `config.py` — `FeedConfig` pydantic model (slug, display_name, url, kind, enabled, poll_interval_minutes — no source_id per D6) + `FeedCatalog` loader with bijection lint (unique slug, unique url). Pattern cloned from `worker.bootstrap.aliases.AliasDictionary`.
  - `feed_state.py` — `rss_feed_state` read/write via sqlalchemy Core. `load_state(session, feed_slug)` + `upsert_state(session, feed_slug, etag, last_modified, last_status_code, last_error, advance_consecutive_failures)`. Uses `INSERT ... ON CONFLICT (feed_slug) DO UPDATE SET ...` (single-row upsert, safe under D2 single-writer assumption).
  - `fetcher.py` — `RssFetcher` class wrapping `httpx.AsyncClient`. Async `fetch(feed: FeedConfig, state: FeedStateRow | None) -> FetchOutcome` — sends `If-None-Match` / `If-Modified-Since` when state present, returns `FetchOutcome(status, content_bytes | None, etag, last_modified, error)`. 304 is a first-class outcome, not an error. Configurable per-request timeout (default 30s), User-Agent (`dprk-cti-worker/<version>`). **Never** calls `feedparser.parse(url)` — only ever passes bytes to the parser.
  - `parser.py` — `parse_feed(content: bytes, kind: Literal["rss", "atom"]) -> ParseOutcome`. Calls `feedparser.parse(content)`. Returns `ParseOutcome(entries: list[RawFeedEntry], parse_error: ParseError | None)` where `parse_error` captures `bozo=1 AND bozo_exception is hard-error` cases. `kind` advisory — feedparser auto-detects but we validate the detected kind matches the config.
  - `normalize.py` — `RawFeedEntry → StagingRowDraft`. URL canonicalization reuses PR #5 `worker.bootstrap.normalize.canonicalize_url`. `sha256_title` reuses the same helper. Title strip/collapse. Published date parsing from `entry.published_parsed` → `datetime` (tz-aware, UTC assumed if missing). Empty-title rows still produce a draft with `title=None` so the D10 `feed.empty_title_rate` metric can count them — they are inserted into staging as-is because staging.title is nullable.
  - `tag_preview.py` — extracts hashtags from entry title + summary, runs them through `worker.bootstrap.normalize.classify_tags`, returns `(total_count, unknown_count)`. Used ONLY to feed the D10 `rss.tags.unknown_rate` metric. Does NOT persist classified tags to staging (no classification until LLM enrichment in Phase 4).
  - `staging_writer.py` — takes `list[StagingRowDraft]` + sqlalchemy session, executes `INSERT INTO staging (...) VALUES (...) ON CONFLICT (url_canonical) DO NOTHING RETURNING id`. Returns `WriteOutcome(inserted_ids, skipped_duplicate_count)`. Audit `staging_insert` events emitted for every returned id (savepoint-wrapped).
  - `runner.py` — `run_rss_ingest(session, catalog, audit_meta, dq_sinks) -> RunOutcome`. Orchestration: load state → fetch → parse → normalize → write → audit → dq. Per-feed failure is isolated (does not abort the run). Per-run counters fed to feed-level DQ.
  - `cli.py` — argparse for two subcommands. `run` (`--database-url` required, `--feeds-path` default `data/dictionaries/feeds.yml`, `--run-id` optional override, `--dq-report-path` optional, `--fail-on {error,warn,none}` default `none` — RSS ingest is inherently warn-dominant). `list-pending` (`--database-url`, `--limit N` default 20, `--json`) — dumps `staging WHERE status='pending'` rows, read-only. Exit codes: 0 on success / warn-only under default `--fail-on none`, 2 on any run-level failure.
  - `flow.py` — `@flow(name="rss-ingest") async def rss_ingest_flow(...)` wraps `run_rss_ingest`. Renames the existing `ingest_sources` stub in `worker.main` to reference this flow; the stub becomes a thin forwarder. No deployment / schedule / worker registration.
- **`services/worker/src/worker/bootstrap/audit.py`** — **zero modifications**. Only `new_uuid7`, `_normalize_for_json`, and `audit_log_table` are imported by the new `worker.ingest.audit` module.
- **`services/worker/src/worker/ingest/audit.py`** — new thin module per D8. `IngestRunMeta` frozen dataclass (`run_id`, `feeds_path`, `started_at` — no `workbook_sha256`). `write_ingest_run_audit()` and `write_staging_insert_audit()` write directly to `audit_log_table` with `actor="rss_ingest"`. 4 action constants (`RSS_RUN_STARTED`, `RSS_RUN_COMPLETED`, `RSS_RUN_FAILED`, `STAGING_INSERT`). ~80 LOC.
- **`services/worker/src/worker/data_quality/expectations/feed_metrics.py`** — new module housing the 4 D10 expectation functions. Follows the `Expectation` wrapper pattern from PR #7 `worker.data_quality.runner`. **Not** registered in `ALL_EXPECTATION_NAMES` / `build_all_expectations` — PR #7's registry is for post-load production checks only. PR #8 expectations are loaded by `worker.ingest.runner` directly from this module, fed with run-level counters in memory (no SQL query — the counters are already aggregated in `RunOutcome`).
- **`services/worker/tests/fixtures/rss/`** — new directory with `sample_rss.xml`, `sample_atom.xml`, `broken.xml`.
- **`services/worker/tests/unit/test_ingest_config.py`** — YAML loader + bijection lint + missing fields + duplicate slug + duplicate URL.
- **`services/worker/tests/unit/test_ingest_fetcher.py`** — `httpx.MockTransport` + ETag round-trip (set ETag → next fetch sends If-None-Match → server returns 304 → state updated without parse) + 500 error path + timeout path + consecutive_failures increment.
- **`services/worker/tests/unit/test_ingest_parser.py`** — happy RSS + happy Atom + broken fixture sets `parse_error` + mismatched kind detected.
- **`services/worker/tests/unit/test_ingest_normalize.py`** — URL canonicalization reuses bootstrap assertions + sha256_title reuse + empty-title still produces a draft with `title=None` + published date TZ handling.
- **`services/worker/tests/unit/test_ingest_tag_preview.py`** — hashtag extraction + unknown rate counting when title has `#malware` (which classify_tags resolves to TAG_TYPE_UNKNOWN per the PR #7 Codex Round 2.1 lesson) + no-tag fallthrough.
- **`services/worker/tests/unit/test_ingest_staging_writer.py`** — sqlite-memory staging. Insert new row → id returned. Insert duplicate url_canonical → skipped counter incremented, no id returned. Mixed batch → partial insert.
- **`services/worker/tests/unit/test_feed_metrics.py`** — 4 expectation functions against synthetic counter dicts, each severity path.
- **`services/worker/tests/integration/test_ingest_runner.py`** — full `run_rss_ingest` against MockTransport + sqlite-memory. Asserts: 1 `rss_run_started` + 1 `rss_run_completed` + N `staging_insert` audit rows; 4 `dq_events` rows with `run_id` matching; idempotent re-run (second call with same fixtures) emits zero new `staging_insert` events (all skipped_duplicate) and still emits the 4 DQ metrics.
- **`services/worker/tests/integration/test_ingest_cli.py`** — CLI exit code matrix (`run` clean → 0, `run --fail-on warn` on warn metric → 2, `list-pending` returns JSON with the right row count).
- **`services/worker/pyproject.toml`** — add `feedparser>=6.0.11` (pure Python, sole new runtime dep). `httpx` already present.
- **`services/worker/src/worker/main.py`** — rename the `ingest_sources` stub to `rss_ingest`, forward to `worker.ingest.flow.rss_ingest_flow`.
- **`services/api/src/api/routers/ingest.py`** — **not modified** in PR #8. Both `POST /ingest/rss/run` and `GET /ingest/status` remain as 501 stubs. API-triggered ingest is a follow-up after the CLI is proven stable. The CLI is the canonical entrypoint.
- **`.github/workflows/ci.yml`** — **extend existing `worker-tests` job**. No new CI job. Add the RSS test modules to the existing pytest invocation. The `data-quality-tests` real-pg job is NOT extended.
- **`services/worker/README.md`** — new "RSS Ingest" runbook section mirroring the PR #7 Data Quality runbook format: CLI invocation examples, flag summary, exit code matrix, 3 `audit_log` + `dq_events` query examples (per-run staging_insert count, recent parse errors, rss_run ↔ dq_events lineage join by run_id), D10 threshold recovery playbook.
- **`DPRK_Cyber_Threat_Dashboard_설계서_v2.0.md`** — errata/pointer updates. §3.4 receives an inline note "PR #8 ships RSS only; TAXII 2.1 split to PR #9." §14 W4 gets the same pointer. Single-source-of-truth in §3.4 + pointers to avoid three-location drift (same pattern as PR #7 D1 errata).
- **`memory/phase_status.md`** — Phase 1.3 section updated with the W4 split note + PR #8 entry.

### Out of scope (explicit — also echoed in §1 Non-goals)

- TAXII 2.1 → PR #9
- Production promote path (staging → reports) → PR #9 / Phase 2
- `POST /reports/review/{id}` approve/reject → Phase 2 Core API (§14 W5)
- Frontend review UI → Phase 2+
- Prefect deployment / schedule / worker infrastructure → dedicated infra PR
- Bootstrap upsert.py ON CONFLICT refactor → remains in `followup_todos.md`, triggered when concurrent production writers arrive
- LLM enrichment (summary, tags_jsonb, embedding, confidence) → Phase 4
- staging row row-level DQ → deferred
- PR #7 expectation registry extension → explicitly rejected per D9
- Rate limiting on admin ingest endpoints → Phase 2 read API hardening
- `sources` table column additions for feed state → rejected per D7
- New `data-quality-tests` real-pg CI coverage for RSS → rejected per D11 / E
- `POST /ingest/rss/run` API stub wiring → follow-up after CLI is proven stable (scope creep risk too high for PR #8; CLI is the canonical entrypoint)
- Node.js 20 GHA action bump → separate cleanup PR (deadline 2026-06-02)
- Automatic feed disable on `consecutive_failures >= N` → recorded in table but not acted on in PR #8

---

## 4. Task Breakdown

Dependency order. Tasks within the same group can be parallelized during implementation.

**Group A — Feed config**
- **T1**: `data/dictionaries/feeds.yml` — 5 initial vendor feeds per D6 (slug / display_name / url / kind / enabled=true / poll_interval_minutes). No `source_id` field — staging.source_id is always NULL per D6.
- **T2**: `worker.ingest.config` — `FeedConfig` pydantic model, `FeedCatalog` loader with bijection lint. Wheel force-include entry in `pyproject.toml` mirroring `aliases.yml` pattern.
- **T3**: `tests/unit/test_ingest_config.py` — loader happy + 4 failure modes (missing field / duplicate slug / duplicate url / malformed YAML).

**Group B — Migration 0006 + fetcher infrastructure**
- **T4**: `db/migrations/versions/0006_rss_feed_state.py` — `rss_feed_state` table per D7. Reversibility verified locally via upgrade → downgrade → upgrade.
- **T5**: `db/migrations/tests/test_0006_rss_feed_state.py` — migration reversibility test (schema-identical round-trip).
- **T6**: `services/worker/src/worker/bootstrap/tables.py` — sqlite mirror for `rss_feed_state` (dialect-agnostic, same pattern as `dq_events` from PR #7).
- **T7**: `worker.ingest.feed_state` — load/upsert helpers using sqlalchemy Core. Single-row `ON CONFLICT (feed_slug) DO UPDATE` (safe under D2 single-writer assumption).
- **T8**: `worker.ingest.fetcher` — `RssFetcher` class. httpx AsyncClient wrap. ETag / Last-Modified header injection. 304 as first-class outcome. Configurable timeout (30s default) and User-Agent. Explicit decoupling: only ever returns bytes — never calls `feedparser.parse(url)`.
- **T9**: `tests/unit/test_ingest_fetcher.py` — `httpx.MockTransport` covering 200+body, 304 (no body), 500, timeout (via `httpx.TimeoutException`), network error, ETag round-trip (state roundtrip + If-None-Match injection), consecutive_failures increment on failure paths.

**Group C — RSS parsing, normalization, staging writer**
- **T10**: `worker.ingest.parser` — `parse_feed(content, kind)`, feedparser bytes-only call path, bozo-error detection (only hard errors count as parse_error; benign warnings like `CharacterEncodingOverride` are ignored), kind mismatch detection.
- **T11**: `tests/unit/test_ingest_parser.py` — happy RSS, happy Atom, broken payload, benign warning payload (should NOT be classified as parse_error), kind mismatch.
- **T12**: `worker.ingest.normalize` — `RawFeedEntry → StagingRowDraft`. Reuses `worker.bootstrap.normalize.canonicalize_url` and `sha256_title`. Empty-title handling: keeps the row with `title=None` so it counts toward `feed.empty_title_rate`. Published-date TZ normalization (assume UTC if feedparser returns a naive `entry.published_parsed`).
- **T13**: `tests/unit/test_ingest_normalize.py` — URL canonicalization reuses bootstrap's fixture assertions, sha256_title reuse, empty-title path, TZ-aware vs naive published date, missing published field.
- **T14**: `worker.ingest.tag_preview` — hashtag extraction regex + `classify_tags` reuse + `(total, unknown)` count return.
- **T15**: `tests/unit/test_ingest_tag_preview.py` — hashtag extraction, unknown-rate counting with known `#malware → TAG_TYPE_UNKNOWN` fallback (from PR #7 Codex Round 2.1 lesson), empty-input fallthrough.
- **T16**: `worker.ingest.staging_writer` — `INSERT INTO staging ... ON CONFLICT (url_canonical) DO NOTHING RETURNING id`, returns `WriteOutcome(inserted_ids, skipped_duplicate_count)`. Batch-friendly (500-row chunking mirrors PR #5/#7 patterns).
- **T17**: `tests/unit/test_ingest_staging_writer.py` — sqlite-memory. New row returns id. Duplicate url_canonical returns None and increments skipped. Mixed batch partial insert. Batch of 1000 chunked correctly.

**Group D — Prefect flow + CLI**
- **T18**: `worker.ingest.runner` — `run_rss_ingest(session, catalog, audit_meta, dq_sinks) -> RunOutcome`. Orchestration with per-feed failure isolation. Per-run counter aggregation feeding into D10 metrics.
- **T19**: `worker.ingest.flow` — `@flow(name="rss-ingest")` decoration on an async wrapper around `run_rss_ingest`.
- **T20**: `worker.main` — rename `ingest_sources` stub to `rss_ingest`, forward to the new flow. Remove the `"RSS/TAXII ingest scaffold ready"` log line.
- **T21**: `worker.ingest.cli` — argparse for `run` + `list-pending` subcommands. Run: `--database-url`, `--feeds-path`, `--run-id`, `--dq-report-path`, `--fail-on {error,warn,none}` default `none`. List-pending: `--database-url`, `--limit`, `--json`. ASCII-only stdout per PR #7 cp949 lesson.
- **T22**: `worker.ingest.__main__` — wire subcommands.
- **T23**: `tests/integration/test_ingest_runner.py` — full run against MockTransport + sqlite-memory. Asserts audit counts (1 started, 1 completed, N staging_insert), 4 dq_events rows, idempotent second run (zero new staging_inserts, all skipped_duplicate, still 4 dq_events).

**Group E — Audit + pre-ingest DQ**
- **T24**: `worker.ingest.audit` — new thin module per D8. `IngestRunMeta` frozen dataclass, `write_ingest_run_audit()`, `write_staging_insert_audit()`, 4 action constants. Imports `new_uuid7`, `_normalize_for_json`, `audit_log_table` from `worker.bootstrap.audit`. **Zero changes to `worker.bootstrap.audit`.**
- **T25**: `tests/unit/test_ingest_audit.py` — exercises `write_ingest_run_audit` (started/completed/failed shapes, actor="rss_ingest", entity="rss_run") + `write_staging_insert_audit` (entity="staging", entity_id=staging.id, diff_jsonb contains url_canonical + meta) against sqlite-memory `audit_log_table`. Verifies `IngestRunMeta` rejects timezone-naive `started_at`.
- **T26**: `worker.data_quality.expectations.feed_metrics` — 4 D10 expectation functions, each accepts a counter dict and returns `ExpectationResult`. Wrapped as `Expectation` instances. **Not** added to `ALL_EXPECTATION_NAMES` — they are invoked directly by `worker.ingest.runner`.
- **T27**: `tests/unit/test_feed_metrics.py` — 4 × (pass / warn) paths, name prefix assertion (`feed.*` / `rss.*`), severity assertion (all warn).
- **T28**: Runner integration (within T18) — wire the 4 metrics into the `run_rss_ingest` tail so they emit through the existing DQ sinks with the shared `run_id`.

**Group F — CI + docs**
- **T29**: `.github/workflows/ci.yml` — extend `worker-tests` pytest invocation to include the new test modules. No new job. If RSS test runtime noticeably grows the `worker-tests` wall time (>30s regression), note in the PR description for a follow-up split.
- **T30**: Design doc v2.0 errata — §3.4 inline note (PR #8 RSS only / PR #9 TAXII) + §14 W4 pointer. Single source of truth in §3.4.
- **T31**: `services/worker/README.md` — new "RSS Ingest" runbook section with CLI invocations, flag summary, exit code matrix, 3 audit_log / dq_events query examples, D10 threshold recovery playbook.
- **T32**: `memory/phase_status.md` — update Phase 1.3 section to reflect the W4 split and PR #8 scope boundaries (post-merge update — not a commit inside this PR).

---

## 5. Risks

| ID | Risk | Impact | Mitigation |
|:---:|:---|:---|:---|
| **R1** | `feedparser` adds a new dep with a slow release cadence and idiosyncratic bozo semantics | Small — feedparser has no transitive deps and is pure Python. The bozo semantics are mitigated by the D10 "hard error only" filter in T10. | Pin `>=6.0.11` (current stable), document the benign-warning ignore list in T10. |
| **R2** | `httpx.MockTransport` behavioral drift from real-world HTTP (ETag casing / redirect semantics / chunked encoding) | Medium — CI green ≠ production green if real vendors do something nonstandard. | Document that first real-feed run post-merge is a manual smoke (same pattern as PR #7 real-workbook deferral). Capture any divergence as a follow-up. The fetcher is the only layer this affects. |
| **R3** | `rss_feed_state` could diverge from `sources` table lifecycle if vendor relationships change (feed retired but vendor still sourced elsewhere) | Operational — wasn't a blocker in PR #7, similar deferral risk here. | D7 explicitly documents this as the reason for a separate table. `consecutive_failures` column supports a future "auto-disable" policy without schema churn. |
| **R4** | Single-writer assumption (D2) may silently break if a future PR wires the admin `POST /ingest/rss/run` to invoke the CLI without a lock | Concurrency race returns the moment two CLIs run simultaneously. Staging UNIQUE constraint would still hold, but `rss_feed_state` upsert could race. | API stub wiring is explicitly out of scope for PR #8. Document in the README runbook (T31): "do not run two CLI instances in parallel until `rss_feed_state` gets a row-level lock or the promotion path arrives." |
| **R5** | `feedparser.parse(bytes)` treats some malformed payloads as 'parse succeeded with 0 entries' rather than bozo — empty result masks a real parse failure | Silent drop risk | Runner treats `parsed_entries == 0 AND fetch_status == 200` as a distinct warn-level signal (can fold into `feed.parse_error_rate` or add a 5th metric; T18 decides at implementation time based on first-fixture observations). |
| **R6** | Codex reviewer may flag "why isn't bootstrap upsert converted to ON CONFLICT in this PR" given the PR #5/#6 comment | Extra review round | Plan doc §2 D4 explicitly addresses this — cite the plan in the PR description. Pattern works (tested on PR #7 V2/V3 backward-compat alias constraint). |
| **R7** | `data/dictionaries/feeds.yml` real-vendor URLs may 404 before PR #8 merges (vendors change URLs) | CI is unaffected (tests use MockTransport), but the first real-run smoke breaks | Accept as first-run operational friction. Initial feed list is a starting point, not a contract. |
| **R8** | pytest `worker-tests` runtime regression from the new suites | CI wall-time growth | Sqlite-memory is fast; the new tests are ~20 unit + 2 integration. Expected delta <15s. If >30s, note in PR description for follow-up. |

---

## 6. Acceptance Criteria

PR #8 is mergeable when:

1. Migration 0006 up/down round-trip passes on `pgvector/pgvector:pg16` locally and in the CI `db-migrations` job.
2. `python -m worker.ingest run --database-url <sqlite-memory> --feeds-path data/dictionaries/feeds.yml --fail-on none` exits 0 against MockTransport-backed sqlite-memory integration test (CI `worker-tests` job). Real-pg coverage is a post-merge manual smoke, not a CI guarantee.
3. `python -m worker.ingest list-pending --database-url <sqlite-memory> --limit 5 --json` returns a JSON array with the expected row count in the integration test.
4. `staging` contains N new rows with `status='pending'`, `source_id=NULL` (always NULL per D6 — vendor linking deferred to promote/review PR), LLM-filled columns NULL, `url_canonical` unique.
5. `audit_log` contains, for a first fixture run: exactly 1 `rss_run_started` + 1 `rss_run_completed` + N × `staging_insert` + 0 `rss_run_failed`.
6. Idempotent second run against the same fixtures produces 0 new `staging_insert` rows, 1 new `rss_run_started` + 1 new `rss_run_completed`, and still emits the 4 DQ metrics with the new `run_id`.
7. Forced all-feed failure (MockTransport 500 on every feed) produces 1 `rss_run_failed` with `all_feeds_failed: true` in `detail`, no leaked `staging_insert` rows, and `feed.fetch_failure_rate` metric at 1.0.
8. `dq_events` contains 4 rows per run with the `feed.*` / `rss.*` name prefix, each with the run's `run_id`, each with severity `warn` or `pass`, each joinable to `audit_log` via `run_id`.
9. `worker-tests` CI job remains green with the new test modules. Wall time delta ≤ 30s.
10. pytest coverage: `services/worker/src/worker/ingest/` ≥ 85%; new expectation module ≥ 90%.
11. `tests/integration/test_ingest_runner.py` asserts the D2 invariant: **zero writes** land on `sources`, `reports`, `tags`, `groups`, `codenames`, `incidents` during a full run (post-run row-count snapshot against a seeded baseline).
12. `data/dictionaries/feeds.yml` loads with bijection lint clean.
13. Codex review clean (expect 2–5 rounds per `memory/feedback_codex_iteration.md`).
14. Design doc v2.0 §3.4 errata + §14 W4 pointer merged in the same PR.
15. No modifications to PR #7's post-load expectation registry (`ALL_EXPECTATION_NAMES` / `build_all_expectations`) — D9 guarantee.
16. No modifications to `worker.bootstrap.upsert` entity write paths — D4 guarantee.
17. No modifications to `worker.bootstrap.audit` signatures or constants — D8 guarantee. Only `new_uuid7`, `_normalize_for_json`, and `audit_log_table` are imported by the new `worker.ingest.audit` module.

---

## 7. Open Items Resolution Log

All D1–D11 locked via 2026-04-16 discuss-phase. Pre-plan-draft discussion covered the user's 5 explicit questions (Q1–Q5) and 7 Claude-raised additional items (A–G). No open items remain before draft.

| Q / Item | Resolution | Locked as |
|:---:|:---|:---:|
| Q1 (RSS + TAXII split?) | Split. RSS in PR #8, TAXII in PR #9. §14 W4 explicitly annotated. | **D1** |
| Q2 (Prefect scope) | `@flow` + local CLI only. No deployment/schedule/worker infra. | **D3** |
| Q3 (ON CONFLICT prereq?) | Conditional accept. RSS worker writes only to `staging`; staging uses `ON CONFLICT (url_canonical) DO NOTHING`. Bootstrap-wide refactor stays deferred. | **D2 + D4** |
| Q4 (Promote in this PR?) | No promote. Staging write + `list-pending` read only. | **D2** |
| Q5 (DQ/audit reuse depth) | audit_log + run_id reused fully. dq_events reused for run-level/feed-level only. No row-level DQ. No PR #7 registry extension. | **D8 + D9** |
| A (Feed config location) | `data/dictionaries/feeds.yml`. | **D6** |
| B (HTTP client) | httpx fetch + feedparser.parse(bytes). Never `feedparser.parse(url)`. | **D5** |
| C (ETag/Last-Modified cache location) | New `rss_feed_state` table via migration 0006. Not a `sources` column. | **D7** |
| D (Test strategy) | Static XML fixtures + httpx.MockTransport + sqlite-memory. No network. | **D11** |
| E (CI job) | Extend `worker-tests`. No new job. | **D11** |
| F (Rate limiting) | Out of scope. Stays in `followup_todos.md`. | — |
| G (`tags.type.unknown_rate` placement) | Rename to `rss.tags.unknown_rate`, document as "staging enrichment / classifier preview," keep separate from PR #7's production `tags.type.enum_conformance`. | **D10** |

### 7.1 Validation Checklist (executed 2026-04-16 pre-lock)

| # | Check | Result | Detail |
|:---:|:---|:---:|:---|
| 1 | Every D-decision addresses a concrete risk or scope boundary | ✅ | 11/11 traceable to one of the Q/item list above |
| 2 | D2 guarantee is mechanically verifiable in tests | ✅ | Acceptance criterion 11 — row-count snapshot against production tables |
| 3 | D4 (no bootstrap refactor) is verifiable via diff | ✅ | Acceptance criterion 16 — `upsert.py` entity write paths unchanged |
| 4 | D5 "no `feedparser.parse(url)`" is verifiable via codebase grep | ✅ | Static check: `grep -r 'feedparser.parse(' services/worker/src/` — every call passes a `bytes` variable |
| 5 | D9 "no PR #7 registry extension" is verifiable via diff | ✅ | Acceptance criterion 15 — `ALL_EXPECTATION_NAMES` / `build_all_expectations` unchanged |
| 6 | D10 expectation names use `feed.*` / `rss.*` prefix, no collision with PR #7 | ✅ | 4/4 prefixed; PR #7 names audited: `groups.*`, `reports.*`, `codenames.*`, `incident_countries.*`, `tags.type.enum_conformance`, `incidents.*` — no overlap with `feed.*` / `rss.*` |
| 7 | Every DQ threshold has a concrete numeric value | ✅ | 0.20 / 0.10 / 0.05 / 0.30 — no vague language |
| 8 | Every operator-actionable failure/warn path has a runbook pointer | ⚠ partial | README runbook ships in T31 covering 4 warn metrics + threshold recovery playbook. First-real-feed post-merge smoke deferred (same pattern as PR #7 §8 step 9; this plan's §8 step 10). |
| 9 | D1 split is documented in `memory/phase_status.md` | ⚠ pending | T32 updates phase_status post-merge |
| 10 | No new runtime dep beyond `feedparser` | ✅ | httpx already present; single new dep verified via `pyproject.toml` diff |

---

## 8. Rollout Plan

Per the PR #4/#5/#6/#7 pattern established in memory:

1. **Plan lock** — this document → mark Locked after user review of D1–D11.
2. **Branch** — `feat/p1.3a-rss-ingest` off `main`.
3. **First commit** — the locked plan doc (this file) so the rollback unit is trivial.
4. **Implementation** — Groups A → B → C → D → E → F in order. Within each group, tasks can parallelize where independent. Groups B and C can interleave: C depends on the sqlite-memory pattern from PR #5 (already on main), not on B's migration.
5. **Self-review** — run `cd services/worker && python -m uv run pytest tests/ -q` before pushing each group. All acceptance criteria 2–12 run against sqlite-memory per D11. Real-pg verification is deferred to step 10 (post-merge manual smoke).
6. **Codex review** — `codex review --base main --title "PR #8 — RSS ingest → staging"`. Expect 2–5 rounds. Apply `memory/feedback_codex_iteration.md` discipline: every finding is fixed, not argued.
7. **User manual review** — in parallel with Codex, per `memory/review_discipline.md`.
8. **Merge** — **merge commit** (not squash) per PR #7 precedent — per-group + per-Codex-finding history has tracking value.
9. **Post-merge** — `memory/phase_status.md` update (T32), `memory/followup_todos.md` closures (the PR #7-era "pre-ingest DQ checks for RSS/TAXII" note gets closed by this PR), new followup entries for any deferred items identified during review.
10. **Post-merge smoke (deferred, tracked)** — first real-feed run against `data/dictionaries/feeds.yml` with a real pg. Any threshold divergence opens a retuning follow-up. This is the RSS analog of PR #7's manual real-workbook smoke.

---

## 9. References

- Design doc v2.0: §1.3 (in/out of scope), §3.4 (RSS/TAXII ingest, current wording), §5.1 (API routing, ingest.rss.run), §6.1 F-7 (human-in-the-loop review), §9.4 (Repudiation / audit), §10.6 (staging 30-day auto-purge), §14 W4 (Phase 1 roadmap), §14.1 (M1 exit)
- Existing schema: `db/migrations/versions/0002_staging_and_indexes.py` — `staging` table with UNIQUE(url_canonical), `status` enum, embedding column, `promoted_report_id` FK
- Existing API stub: `services/api/src/api/routers/ingest.py` — admin-gated `POST /ingest/rss/run` 501 stub
- PR #5 plan: `docs/plans/pr5-bootstrap-etl.md` — alias dictionary / fixture / YAML loader pattern this plan reuses
- PR #7 plan: `docs/plans/pr7-data-quality.md` — audit + dq_events infra this plan reuses (D8, D9)
- PR #7 implementation: `services/worker/src/worker/bootstrap/audit.py` (audit writer + actor/action constants), `services/worker/src/worker/data_quality/` (expectation wrapper + sinks), `services/worker/src/worker/bootstrap/normalize.py` (canonicalize_url, sha256_title, classify_tags)
- Memory: `feedback_codex_iteration.md`, `pitfall_ci_smoke_fixture_semantics.md` (Codex Round 2.1 lesson applied to D10 `rss.tags.unknown_rate` naming), `followup_todos.md` (PR #5/#6 ON CONFLICT defer, PR #7 "pre-ingest DQ for RSS/TAXII" defer to be closed by this PR), `review_discipline.md`, `phase_status.md`

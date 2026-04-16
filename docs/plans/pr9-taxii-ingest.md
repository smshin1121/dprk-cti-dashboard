# PR #9 Plan — Phase 1.3b TAXII 2.1 Ingest Worker → Staging

**Phase:** 1.3b (design doc v2.0 §14 W4 — split: RSS in PR #8, TAXII 2.1 in PR #9).
**Status:** **Locked 2026-04-16.** D1–D6 (user-specified) + A–I (Claude-raised) locked via 2026-04-16 discuss-phase (1 round: initial proposal + user review with 5 modifications + 3 additions).
**Predecessors:** PR #8 (RSS ingest, `feeds.yml`, `staging_writer`, `audit`/DQ infra — merged 2026-04-16 as `9107116`; post-merge smoke at `b824fb9`).
**Successors:** Phase 2 read API (review/promote endpoints), Phase 4 LLM enrichment (summary/embedding fill).

> **§14 W4 split note.** Carried from PR #8: RSS = PR #8 (merged), TAXII 2.1 = PR #9 (this plan). §3.3 errata already updated in PR #8.

---

## 1. Goal

Deliver a **TAXII 2.1 ingest worker** that polls pre-configured TAXII collections (initially 3 MITRE ATT&CK collections), fetches STIX 2.1 envelopes over HTTPS, extracts actionable STIX object types, normalizes each object into a `staging` row, and persists with dedup via `ON CONFLICT (url_canonical) DO NOTHING`. Every run emits audit lineage to `audit_log` and collection-level DQ observations to `dq_events`, sharing the same uuid7 `run_id` interop pattern established in PR #7/PR #8.

**Non-goals (explicit)**:
- **RSS ingest changes** — PR #8 infra is frozen. No modifications to `worker.ingest.{config,fetcher,parser,normalize,runner,cli}`.
- **Production promotion path** (staging → reports/sources/tags write) — deferred to Phase 2 read API, same as PR #8 D2.
- **Auto-discovery of TAXII collections** — deferred. YAML-fixed catalog only (D2).
- **OAuth / mTLS authentication** — deferred. Unauthenticated + basic auth + API-key header only (D1).
- **STIX relationship graph processing** — `relationship` objects are not ingested to staging. Graph construction is Phase 2+.
- **Prefect deployment / schedule / worker infrastructure** — `@flow` + local CLI only, same as PR #8 D3.
- **LLM enrichment** (`staging.summary`, `staging.embedding`) — Phase 4.
- **Node.js 20 GHA action bump** — separate cleanup (deadline 2026-06-02).

---

## 2. Decisions to Lock

### 2.1 User-Specified (6)

| ID | Question | Proposed Position | Rationale |
|:---:|:---|:---|:---|
| **D1** | **Auth scope**: API token / OAuth / mTLS — 이번 PR에 어디까지? | **Unauthenticated + optional basic auth + optional header-based API key. OAuth and mTLS deferred.** MITRE TAXII server requires no auth. `taxii_collections.yml` per-collection config: `auth_type ∈ {none, basic, header_api_key}`. For `basic`: `username`, `password_env` (env var name, e.g., `TAXII_MITRE_PASSWORD`). For `header_api_key`: `auth_header_name` (e.g., `X-Api-Key`), `auth_header_value_env` (env var name). **Secrets are NEVER stored as plaintext in YAML — only env var names.** Loader validates that referenced env vars are set at startup. OAuth needs token refresh flow; mTLS needs cert file management — both add complexity with no current consumer. | MITRE collections are fully public. The optional basic/header_api_key path covers semi-public TAXII servers that may be added later without a schema change. Header name is configurable because TAXII servers use varying header conventions (`X-Api-Key`, `Authorization: Bearer`, `X-TAXII-Token`, etc.). Env-var-only storage follows the same pattern as `--database-url` and prevents accidental secret commit. |
| **D2** | **Collection discovery**: 자동 discovery인지, YAML 고정인지? | **YAML fixed** (`data/dictionaries/taxii_collections.yml`). Auto-discovery deferred. | Same rationale as PR #8 D6: committed YAML is diff-reviewable, git-blame-able, ships with the wheel. Auto-discovery adds network I/O to the config loading path, complicates testing, and is unnecessary when the initial collection set is 3 known MITRE collections. Discovery endpoint support lands when a third-party TAXII server with dynamic collections is actually needed. |
| **D3** | **Write scope**: PR #8처럼 staging-only 유지? | **Staging-only.** Identical guarantee to PR #8 D2. Zero writes to `sources`, `groups`, `codenames`, `reports`, `tags`, `incidents`. `staging.source_id` always NULL. | Same rationale as PR #8 D2: no concurrent writer on production tables until promote paths land. `UNIQUE(url_canonical)` dedup on staging is the only constraint needed. |
| **D4** | **State storage**: `rss_feed_state` 재사용 vs `taxii_collection_state` 분리? | **Separate `taxii_collection_state` table via migration 0007.** Schema: `(collection_key TEXT PK, server_url TEXT NOT NULL, collection_id TEXT NOT NULL, last_added_after TEXT NULL, last_fetched_at TIMESTAMPTZ NULL, last_object_count INTEGER NULL, last_error TEXT NULL, consecutive_failures INTEGER NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())`. | Different lifecycle and semantics from `rss_feed_state`. RSS tracks ETag/Last-Modified (HTTP conditional GET). TAXII tracks `last_added_after` (TAXII-native timestamp filter for incremental polling). PK is `collection_key` (slug from YAML, e.g., `mitre-enterprise-attack`), not a composite, for log readability. `server_url` + `collection_id` stored for operational debugging but not used as PK. |
| **D5** | **DQ metrics namespace**: `taxii.*` 별도 vs `feed.*` 통합? | **`taxii.*` separate namespace.** 4 metrics: (1) `taxii.fetch_failure_rate` — ratio of collections whose GET returned non-2xx/exception, warn at > 0.20. (2) `taxii.stix_parse_error_rate` — ratio of fetched STIX objects that fail structure validation, warn at > 0.10. (3) `taxii.empty_description_rate` — ratio of ingested STIX objects with no `description`, warn at > 0.30. **Warn-only, tuning expected**: STIX objects (especially `attack-pattern`) frequently lack descriptions; this metric may fire consistently on first runs and the threshold is a starting point, not a contract. (4) `taxii.label_unmapped_rate` — ratio of STIX `labels[]` values that don't map to any known tag type in the alias dictionary, warn at > 0.50 (primary coverage metric, see D6). All `warn` severity — TAXII collections are exogenous. | TAXII failure modes are fundamentally different from RSS: no XML parse errors, but STIX structure validation and label coverage are unique concerns. Separate namespace allows `dq_events WHERE expectation LIKE 'taxii.%'` filtering. No collision with PR #8 `feed.*`/`rss.*` or PR #7 production metrics. `empty_description_rate` threshold is intentionally loose — recognized as a low-signal metric on initial data; kept for trend monitoring, not gating. |
| **D6** | **`rss.tags.unknown_rate` redesign**: 폐기 / 대체 / 조건부 계산? | **Redefine the metric concept, then apply per-protocol.** (a) **RSS side**: `rss.tags.unknown_rate` is **deprecated / observational only**. It remains emitted for backward-compatible trend analysis but is downgraded: severity stays `warn`, threshold raised to `1.0` (always-pass), and the metric docstring + README runbook explicitly state `"DEPRECATED — observational only. Hashtag extraction is not meaningful against real vendor feeds. Real tag coverage lands with Phase 4 LLM enrichment."` It is NOT removed (existing dq_events queries should not break), but it is no longer a signal — only a smoke detector for metric computation failures. (b) **TAXII side**: `taxii.label_unmapped_rate` is the **new primary tag coverage metric**. STIX objects carry structured `labels[]` — these ARE the tag vocabulary, so the metric directly measures alias dictionary coverage. Threshold `0.50` (MITRE labels are broad; many won't map to our narrow DPRK-focused dictionary). This is the metric that replaces the concept `rss.tags.unknown_rate` was trying to capture. (c) **Cross-protocol unification** deferred to Phase 4 when LLM generates structured tags for both RSS and TAXII staging rows. | The root problem is that `rss.tags.unknown_rate` assumed feeds use `#hashtag` format, which they don't. Instead of patching the extraction heuristic (NLP is Phase 4), we honestly deprecate the RSS metric and introduce a meaningful STIX-native replacement for TAXII. Keeping the deprecated metric emitting (vs. removing) preserves backward-compatible dq_events queries and provides a clean upgrade path when Phase 4 introduces a unified tag metric. |

### 2.2 Additional Items (Claude-raised)

| ID | Item | Proposed Position | Rationale |
|:---:|:---|:---|:---|
| **A** | **HTTP client**: `taxii2-client` library vs `httpx` direct? | **`httpx` direct — no new dependency.** TAXII 2.1 is HTTP + JSON with `Accept: application/taxii+json;version=2.1` header. The protocol surface needed (GET objects, pagination via `more`/`next`, `added_after` filter) is ~80 LOC over `httpx`. | `taxii2-client` is sync-only (uses `requests`), in maintenance mode (last release 2022), and would require `asyncio.to_thread()` wrapping. `httpx` is already a dep, natively async, and gives us full control over timeout/retry/error classification — consistent with PR #8's fetcher pattern. Zero new runtime deps. |
| **B** | **STIX object type filter**: which types go to staging? | **Configurable per-collection in YAML.** Default whitelist (6 types): `intrusion-set`, `malware`, `attack-pattern`, `tool`, `campaign`, `indicator`. Skip: `relationship`, `identity`, `marking-definition`, `x-mitre-tactic`, `x-mitre-matrix`, `x-mitre-data-source`, `course-of-action`. `indicator` is **explicitly included** — it is common in TAXII collections (IOCs, YARA rules, STIX patterns) and represents actionable CTI that belongs in the staging review queue. | `relationship` objects require graph processing (Phase 2+). `identity`/`marking-definition` are structural metadata. The 6 whitelisted types represent actionable CTI entities that map cleanly to staging rows. Per-collection override in YAML allows narrowing (e.g., a collection that only serves `intrusion-set`) or widening (e.g., adding `report` for a future collection). `indicator` was initially omitted from the draft but added per user review — it is one of the most frequent STIX types in real TAXII collections. |
| **C** | **`url_canonical` for STIX objects**: STIX has no web URL field | **`url_canonical` is ALWAYS the STIX URN: `urn:stix:{type}--{uuid}`.** This is the stable, deterministic dedup key. The `url` column (human-facing, display) is set to the ATT&CK URL from `external_references` where `source_name == "mitre-attack"` if present, otherwise falls back to the same URN. Examples: `url_canonical = "urn:stix:intrusion-set--c93fccb1-..."`, `url = "https://attack.mitre.org/groups/G0032/"` (Lazarus). For objects without ATT&CK reference: `url = url_canonical = "urn:stix:malware--0a3ead4e-..."`. | ATT&CK URLs exist on only a subset of STIX objects — using them as `url_canonical` would create a fragile two-path dedup key. STIX IDs are globally unique by design (UUID v4/v5) and stable across TAXII server versions. The URN scheme guarantees zero collision with RSS entries (different scheme). `url` column provides the human-clickable link when available, without burdening the dedup constraint. `canonicalize_url` from PR #8 is NOT applied to URNs (it expects HTTP URLs); URN values are stored verbatim. |
| **D** | **Initial full pull**: MITRE enterprise-attack has ~15–20K total objects (~1,700 after type filter). Handle gracefully? | **First run is a full pull (no `added_after`). Subsequent runs use `last_added_after` from state table. Writes batched via existing `staging_writer` 500-row chunking. Progress logged per page.** | After type filtering, the first pull is ~1,700 objects — manageable. `staging_writer.write_staging_rows` already handles batching. Per-page progress logging (object count, elapsed) aids operational visibility. No special "bootstrap mode" needed. |
| **E** | **Package structure**: flat in `worker.ingest/` or sub-package? | **Sub-package: `worker.ingest.taxii/`**. Modules: `__init__.py`, `config.py`, `fetcher.py`, `stix_parser.py`, `normalize.py`, `runner.py`, `state.py`, `audit.py`, `cli.py`, `flow.py`. Shared infra imported from parent: `worker.ingest.staging_writer` (reused as-is), `worker.bootstrap.audit` (shared utilities). | Keeps RSS modules at `worker.ingest/*.py` untouched (PR #8 freeze guarantee). Clear separation of protocol-specific code. The sub-package mirrors `worker.ingest/` structure for consistency. |
| **F** | **Audit module**: extend `worker.ingest.audit` or separate? | **Separate `worker.ingest.taxii.audit`** with `TAXII_INGEST_ACTOR = "taxii_ingest"`, action constants `TAXII_RUN_STARTED` / `TAXII_RUN_COMPLETED` / `TAXII_RUN_FAILED` / `STAGING_INSERT`. Own `TaxiiRunMeta(run_id, collections_path, started_at)` frozen dataclass. Imports `new_uuid7`, `_normalize_for_json`, `audit_log_table` from `worker.bootstrap.audit`. | Same thin-module pattern as PR #8 D8. Different actor literal enables `audit_log WHERE actor='taxii_ingest'` filtering. `TaxiiRunMeta.collections_path` replaces `IngestRunMeta.feeds_path`. Zero modifications to `worker.ingest.audit` (RSS audit frozen). |
| **G** | **STIX → staging column mapping** | `name` → `title`, ATT&CK URL or URN → `url` (per C), STIX URN → `url_canonical` (per C), `description` → `raw_text`, `modified` (or `created` if `modified` absent) → `published`, `labels` fed to DQ metric only. `summary` = NULL (LLM-filled), `source_id` = NULL (D3), `tags_jsonb`/`confidence`/`embedding` = NULL (Phase 4). `sha256_title` via existing `sha256_title()` helper. **Semantic mismatch acknowledged**: STIX `modified` is an object update timestamp (when the STIX producer last edited the object), NOT a publication date. It is mapped to `staging.published` as a pragmatic best-effort approximation because the staging schema has no dedicated `updated_at` column. This is a temporary mapping to fit the current schema — if a future migration adds `stix_modified` or `ingested_at` to staging, the mapping should be revised. The mismatch is documented in the normalize module docstring and the README runbook. | `raw_text` is the correct column for raw ingested content (distinct from LLM-generated `summary`). `modified` is the closest available proxy for "when this intelligence was last relevant." `created` is used as fallback only when `modified` is absent (rare in MITRE data). All LLM-filled and promote-filled columns stay NULL per D3. |

| **H** | **`added_after` inclusive/exclusive semantics + overlap window** | **`added_after` is exclusive in TAXII 2.1 spec (objects added strictly AFTER the timestamp are returned). To guard against server-side clock skew and boundary edge cases, the fetcher subtracts a 5-minute overlap window from `last_added_after` before sending.** On first run (no state): `added_after` is omitted entirely (full pull). On subsequent runs: `added_after = last_added_after - 5 minutes`. The overlap means some objects may be re-fetched — `ON CONFLICT (url_canonical) DO NOTHING` deduplicates them silently. The 5-minute window is a constant in `worker.ingest.taxii.fetcher`, documented in the module docstring. | TAXII 2.1 spec (Section 5.7) defines `added_after` as exclusive: "only return objects added after this timestamp." However, real-world TAXII servers vary in boundary interpretation (some are inclusive, some have clock skew). A 5-minute overlap is cheap (re-fetches a few dozen objects at most) and eliminates the risk of missing objects at the boundary. `staging_writer`'s `DO NOTHING` dedup absorbs the overlap cost with zero side effects. |
| **I** | **Pagination support** | **Mandatory. The fetcher MUST follow `more`/`next` pagination to completeness.** When the TAXII envelope contains `"more": true`, the fetcher sends a follow-up request with the `next` parameter until `"more": false` or `next` is absent. Page size is server-controlled (no client-side `limit` parameter in TAXII 2.1). Each page is processed independently (objects extracted, validated, normalized, written) before fetching the next page — this bounds memory usage for large collections. A per-collection configurable `max_pages` safety limit (default 100) prevents runaway pagination against misbehaving servers. | MITRE enterprise-attack contains ~15–20K total objects. Without pagination, a single GET returns an incomplete or oversized response. The TAXII 2.1 spec requires clients to handle pagination. Processing per-page (not buffering all pages) keeps memory bounded even for the initial full pull. `max_pages = 100` is a safety valve — at typical page sizes of 200–500 objects, this covers 20K–50K objects, well beyond any single MITRE collection. |

---

## 3. Scope

### In scope

- **Migration 0007** — `taxii_collection_state` per D4.
- **`data/dictionaries/taxii_collections.yml`** — 3 initial MITRE collections per D2. Schema per entry: `slug`, `display_name`, `server_url`, `api_root_path`, `collection_id`, `auth_type ∈ {none, basic, header_api_key}` (default `none`), `username` / `password_env` (for `basic`), `auth_header_name` / `auth_header_value_env` (for `header_api_key`), `stix_types` (whitelist per B, default `[intrusion-set, malware, attack-pattern, tool, campaign, indicator]`), `enabled`, `poll_interval_minutes`, `max_pages` (default 100, per I).
- **`worker.ingest.taxii/`** sub-package (new, per E):
  - `config.py` — `TaxiiCollectionConfig` pydantic model + `TaxiiCatalog` loader with bijection lint. Pattern from `worker.ingest.config`.
  - `fetcher.py` — `TaxiiFetcher` class wrapping `httpx.AsyncClient`. Sends `Accept: application/taxii+json;version=2.1`. Validates response `Content-Type` (non-TAXII responses = hard error per PR #8 NonXMLContentType lesson). Handles mandatory pagination (`more`/`next`, per I) with per-page processing and `max_pages` safety limit. `added_after` parameter for incremental polling with 5-minute overlap window subtraction (per H). Auth header injection per D1 (none/basic/header_api_key).
  - `stix_parser.py` — validates envelope structure, extracts objects matching the type whitelist, rejects malformed objects.
  - `normalize.py` — STIX object → `StagingRowDraft` per mapping G. `url_canonical` = STIX URN (per C). `url` = ATT&CK URL or URN fallback (per C). `modified` → `published` with semantic mismatch documented (per G). `description` → `raw_text`.
  - `state.py` — `taxii_collection_state` read/write. `load_state(session, collection_key)` + `upsert_state(session, ...)`.
  - `runner.py` — `run_taxii_ingest(session, catalog, fetcher, ...)` orchestration with per-collection failure isolation. Pattern from `worker.ingest.runner`.
  - `audit.py` — thin module per F. `TaxiiRunMeta`, `write_taxii_run_audit`, `write_staging_insert_audit`.
  - `cli.py` — `python -m worker.ingest.taxii run` + `list-pending` (reuses RSS `list-pending` or shares via parent `worker.ingest.cli`). `--collections-path`, `--database-url`, `--run-id`, `--fail-on`.
  - `flow.py` — `@flow(name="taxii-ingest")` wrapper.
  - `__init__.py`, `__main__.py`.
- **`worker.ingest.staging_writer`** — reused as-is (zero modifications).
- **`worker.data_quality.expectations.taxii_metrics.py`** — 4 D5 expectation functions. Not added to `ALL_EXPECTATION_NAMES`.
- **Tests** — static STIX JSON fixtures + `httpx.MockTransport` + sqlite-memory. Pattern from PR #8 D11.
  - `tests/fixtures/taxii/` — `sample_envelope.json` (valid STIX objects), `empty_envelope.json`, `paginated_envelope_p1.json` + `_p2.json`, `malformed_object.json`.
  - Unit tests for config, fetcher, stix_parser, normalize, state, audit, taxii_metrics.
  - Integration test for runner (full pipeline against MockTransport + sqlite-memory).
  - CLI exit code matrix test.
- **CI** — extend `worker-tests` job. No new CI job.
- **Design doc errata** — §3.3 "TAXII 2.1: taxii2-client" corrected to "TAXII 2.1: httpx" per decision A.
- **`rss.tags.unknown_rate` deprecated** — per D6(a): threshold raised to `1.0`, docstring + README updated to `"DEPRECATED — observational only"`. Single edit in `feed_metrics.py` + README runbook note.

### Out of scope (explicit)

- RSS ingest module changes (beyond D6 deprecation edit in `feed_metrics.py`) → frozen
- TAXII collection auto-discovery → follow-up
- OAuth / mTLS authentication → follow-up
- `relationship` / `identity` / `marking-definition` ingestion → Phase 2+ graph
- Production promote path → Phase 2
- Prefect deployment → dedicated infra PR
- LLM enrichment → Phase 4
- ON CONFLICT refactor on bootstrap upsert → same deferral as PR #8
- `rss.tags.unknown_rate` extraction rework (keyword NLP replacement) → Phase 4 LLM
- TAXII collection auto-discovery endpoint support → follow-up when dynamic-collection server is added
- `added_after` overlap window tuning (5-min is starting point) → adjust after first real-run operational data

---

## 4. Task Breakdown (finalized 2026-04-16)

Implementation order per user review — 7 groups, reordered from the preliminary 6 to separate fetcher (C) from normalize (D) and move CLI/flow (F) after audit/DQ (E).

**Group A — YAML / config / auth schema**
- T1: `data/dictionaries/taxii_collections.yml` — 3 MITRE collections with auth_type=none.
- T2: `worker.ingest.taxii.config` — `TaxiiCollectionConfig` pydantic model (slug, display_name, server_url, api_root_path, collection_id, auth_type ∈ {none, basic, header_api_key}, username/password_env, auth_header_name/auth_header_value_env, stix_types, enabled, poll_interval_minutes, max_pages). `TaxiiCatalog` loader with bijection lint (unique slug, unique server_url+collection_id pair). Auth validation: basic requires username+password_env; header_api_key requires auth_header_name+auth_header_value_env. Wheel force-include.
- T3: `tests/unit/test_taxii_config.py` — loader happy + 6 failure modes (missing field, duplicate slug, duplicate server+collection, invalid auth_type, basic auth missing password_env, header_api_key missing header_name).

**Group B — Migration 0007 + state management**
- T4: `db/migrations/versions/0007_taxii_collection_state.py` — `taxii_collection_state` per D4. Reversible.
- T5: sqlite mirror in `worker.bootstrap.tables`.
- T6: `worker.ingest.taxii.state` — `load_state(session, collection_key)` + `upsert_state(session, ...)`.
- T7: `tests/unit/test_taxii_state.py` — load empty, upsert+reload, consecutive_failures increment, reset on success.

**Group C — TAXII fetcher + pagination + added_after overlap**
- T8: `worker.ingest.taxii.fetcher` — `TaxiiFetcher` wrapping `httpx.AsyncClient`. `Accept: application/taxii+json;version=2.1`. Content-Type validation (non-TAXII = hard error). Mandatory pagination (`more`/`next` per I, `max_pages` safety). `added_after` with 5-min overlap subtraction (per H). Auth header injection per D1. Per-page yield (not buffer-all).
- T9: `tests/unit/test_taxii_fetcher.py` — MockTransport: single-page 200, multi-page (3 pages), `max_pages` exceeded (infinite `more=true`), empty collection, `added_after` overlap window verification, auth header injection (none/basic/header_api_key), Content-Type rejection (HTML), 500 error, timeout.

**Group D — STIX parser + normalize + staging writer reuse**
- T10: `worker.ingest.taxii.stix_parser` — envelope validation, type filter (6 types per B incl. `indicator`), malformed object rejection (missing `id`/`type`/`name`).
- T11: `worker.ingest.taxii.normalize` — STIX object → `StagingRowDraft`. `url_canonical` = `urn:stix:{type}--{uuid}` always (per C). `url` = ATT&CK URL or URN fallback (per C). `modified` → `published` with semantic mismatch docstring (per G). `description` → `raw_text`. `sha256_title` via existing helper.
- T12: `tests/unit/test_stix_parser.py` — valid envelope, type filter (relationship excluded, indicator included), malformed object, empty objects list.
- T13: `tests/unit/test_taxii_normalize.py` — happy path with ATT&CK URL, fallback URN, missing description → `raw_text=None`, missing modified → created fallback, `sha256_title` consistency, empty name.

**Group E — Audit + DQ**
- T14: `worker.ingest.taxii.audit` — thin module per F. `TaxiiRunMeta`, `TAXII_INGEST_ACTOR`, `TAXII_RUN_STARTED`/`COMPLETED`/`FAILED`, `STAGING_INSERT`. Imports shared utils from `worker.bootstrap.audit`.
- T15: `worker.data_quality.expectations.taxii_metrics` — 4 D5 expectation functions.
- T16: `feed_metrics.py` D6 deprecation (`rss.tags.unknown_rate` threshold → 1.0, docstring → "DEPRECATED — observational only").
- T17: `tests/unit/test_taxii_audit.py` + `tests/unit/test_taxii_metrics.py`.

**Group F — Runner + CLI + flow**
- T18: `worker.ingest.taxii.runner` — `run_taxii_ingest(session, catalog, fetcher, ...)` orchestration with per-collection failure isolation. Per-run counters fed to D5 metrics. **Continuously verify**: url_canonical is always URN; added_after overlap dedup is silent; partial collection failure produces correct audit.
- T19: `worker.ingest.taxii.cli` — `python -m worker.ingest.taxii run` + `list-pending`. `--collections-path`, `--database-url`, `--run-id`, `--fail-on`.
- T20: `worker.ingest.taxii.flow` + `__main__`.
- T21: `tests/integration/test_taxii_runner.py` — full pipeline against MockTransport + sqlite-memory. Asserts: audit counts, dq_events, idempotent second run, partial failure audit consistency.
- T22: `tests/integration/test_taxii_cli.py` — CLI exit code matrix.

**Group G — CI + docs**
- T23: `.github/workflows/ci.yml` — extend `worker-tests`.
- T24: Design doc errata (§3.3 `taxii2-client` → `httpx`).
- T25: `services/worker/README.md` — TAXII runbook section + RSS `unknown_rate` deprecated note.
- T26: `memory/phase_status.md` update (post-merge).

---

## 5. Risks (preliminary)

| ID | Risk | Impact | Mitigation |
|:---:|:---|:---|:---|
| R1 | MITRE TAXII server may change API structure or go offline | Medium — CI unaffected (MockTransport), but real-feed smoke breaks | Same as PR #8 R7: accept as first-run operational friction. MITRE has been stable for years. |
| R2 | STIX object schema drift (new fields, deprecated fields) between MITRE ATT&CK versions | Low — normalize only reads known fields, ignores extras | Parser uses allowlist of required fields, not strict schema validation. Unknown fields are silently ignored. |
| R3 | Initial full pull of ~1,700 objects may timeout on slow connections | Low — httpx has per-request timeout + pagination breaks work into smaller chunks | Configurable timeout per collection in YAML. Pagination means each HTTP request returns a bounded page. |
| R4 | `taxii2-client` is the design doc's stated library (§3.3), but we're using httpx direct | Documentation drift | Design doc errata in T21 corrects §3.3. Rationale documented in decision A. |
| R5 | STIX `labels[]` vocabulary may have low overlap with our alias dictionary → `taxii.label_unmapped_rate` always at warn | Expected — threshold is intentionally loose (0.50) | Same as PR #8's `rss.tags.unknown_rate` lesson: threshold is a starting point, adjusted after first real run. |
| R6 | URL canonicalization of ATT&CK URLs may produce collisions with future data sources | Very low — ATT&CK URLs are unique per object, URN fallback uses STIX UUID | Canonicalization is deterministic and collision-free within the ATT&CK domain. |
| R7 | PR #8 lessons: Windows SelectorEventLoop, vendor URL drift | Medium — same risks apply to TAXII server URLs | Carry forward: CLI uses SelectorEventLoop on Windows. Post-merge smoke verifies MITRE URLs live. |

---

## 6. Acceptance Criteria (preliminary)

1. Migration 0007 up/down round-trip passes locally and in CI.
2. `python -m worker.ingest.taxii run --database-url <sqlite-memory> --collections-path data/dictionaries/taxii_collections.yml --fail-on none` exits 0 against MockTransport in CI.
3. `staging` contains N new rows with `url_canonical` matching `urn:stix:{type}--{uuid}` pattern (per C), `source_id=NULL`, LLM columns NULL.
4. `audit_log` contains `taxii_run_started` + `taxii_run_completed` + N × `staging_insert` with `actor="taxii_ingest"`.
5. Idempotent second run produces 0 new `staging_insert` rows (all duplicates via URN-based dedup).
6. `dq_events` contains 4 `taxii.*` rows per run.
7. Zero writes to production tables (same D2/D3 invariant as PR #8, verified by row-count snapshot test).
8. Zero modifications to `worker.ingest/*.py` (RSS modules) beyond `feed_metrics.py` D6 deprecation edit.
9. Pagination test: MockTransport serving a 3-page envelope (page 1 `more=true` + `next`, page 2 `more=true` + `next`, page 3 `more=false`) results in all objects across all pages being ingested.
10. `max_pages` safety: MockTransport serving infinite `more=true` is terminated after `max_pages` requests.
11. `added_after` overlap: second run sends `added_after` = `last_added_after - 5min`, and re-fetched objects are silently deduplicated.
12. Auth header injection: MockTransport verifies `Authorization: Basic ...` header when `auth_type=basic`, custom `X-Api-Key` header when `auth_type=header_api_key`, no auth header when `auth_type=none`.
13. STIX type filter: objects of type `relationship` in the test envelope are excluded from staging; `indicator` objects are included.
14. Codex review clean (expect 2–5 rounds per `memory/feedback_codex_iteration.md`).
15. pytest coverage: `worker.ingest.taxii/` >= 85%; `taxii_metrics` >= 90%.
16. `worker-tests` CI wall time delta <= 30s.

---

## 7. PR #8 Lessons Applied

| Lesson | Source | Application in PR #9 |
|:---|:---|:---|
| Vendor URL drift | PR #8 mandiant/RF URL corrections | Post-merge smoke verifies MITRE TAXII URLs live. `taxii_collections.yml` URL stability note in header. |
| Windows ProactorEventLoop | PR #8 psycopg fix | CLI carries forward SelectorEventLoop on Windows. |
| `rss.tags.unknown_rate` meaningless | PR #8 real-feed smoke | D6: threshold → 1.0 on RSS side. TAXII side uses STIX-native labels (meaningful metric). |
| Codex review 3–6 rounds | PR #7/PR #8 pattern | Budget for 3–5 rounds. Never merge on round 1. |
| `staging.summary` = NULL | PR #8 Codex R1 | STIX `description` → `raw_text` (not `summary`). `summary` stays NULL. |
| NonXMLContentType masking | PR #8 Codex R3 | TAXII uses JSON, not XML — but same principle: validate `Content-Type: application/taxii+json` before parsing. Non-TAXII responses (HTML login pages, WAF blocks) classified as hard errors. |

---

## 8. References

- Design doc v2.0: §3.3 (TAXII 2.1 ingest, `taxii2-client` → httpx per A), §6.2 (Tampering — HTTPS + signature verification), §7.2 (Container architecture — worker container), §9.4 (Repudiation — audit_log), §10.6 (staging 30-day purge), §14 W4 (Phase 1 roadmap)
- MITRE ATT&CK TAXII server: discovery `https://cti-taxii.mitre.org/taxii2/`, API root `https://cti-taxii.mitre.org/stix/`, collections: `enterprise-attack`, `mobile-attack`, `ics-attack` (unauthenticated, read-only)
- TAXII 2.1 spec: HTTP + JSON, `Accept: application/taxii+json;version=2.1`, envelope pagination via `more`/`next`, incremental polling via `added_after` timestamp
- PR #8 plan: `docs/plans/pr8-rss-ingest.md` — reusable infra (staging_writer, audit pattern, DQ sinks, CLI structure)
- PR #8 implementation: `worker.ingest/` (11 modules), `worker.data_quality.expectations.feed_metrics`, `data/dictionaries/feeds.yml`
- Memory: `feedback_codex_iteration.md`, `pitfall_vendor_feed_url_drift.md`, `pitfall_windows_psycopg_eventloop.md`, `followup_todos.md`

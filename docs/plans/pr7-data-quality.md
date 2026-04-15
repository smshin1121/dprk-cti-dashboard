# PR #7 Plan — Phase 1.2 Data Quality Gate (pytest + SQL) + audit row-level (ETL)

**Phase:** 1.2 (design doc v2.0 §3.2, §12, §14 W3 — data quality + row-level lineage). Resequenced after 1.4 per dependency order: data first, then gates.
**Status:** **Locked 2026-04-15.** D1–D9 locked via discuss-phase round 1. D10–D13 locked via discuss-phase round 2 after Claude-authored OI1–OI4 draft + user approval with V2/V3 backward-compat alias constraint. Changes after this point require an explicit scope-change note in the implementing PR description.
**Predecessors:** PR #3 (CI pytest gate), PR #4 (BigInt PK preflight), PR #5 (ETL normalize + upsert library), PR #6 (ETL CLI + dead-letter + worker-tests CI) — all merged as of 2026-04-15.
**Successors:** PR #8 (RSS/TAXII worker + Prefect — will reuse DQ CLI as post-ingest gate; may introduce pre-ingest DataFrame checks out of this plan's scope).

---

## 1. Goal

Deliver a **pytest-based data quality gate** that runs against the Bootstrap ETL output in a real Postgres instance, emits row-level and run-level lineage to `audit_log`, and records quality observations to a purpose-built `dq_events` table. The gate runs in CI against the committed fixture, and is invocable locally / in operator runbooks as `python -m worker.data_quality check`.

**Non-goals (explicit):**
- Great Expectations framework (see D1 — replaced by pytest + SQL, with design doc errata).
- In-memory / sqlite / DataFrame-level DQ fallback (see D7 — PG-only).
- Pre-ingest DQ checks for RSS/TAXII workers (deferred to PR #8).
- Grafana dashboards for DQ trend (deferred to Phase 3+ observability work — only a CLI `report` stub lands in PR #7 per D8).
- LLM-based quality heuristics (Phase 4).
- Frontend changes.
- Audit row-level for any non-ETL write path (see D3 scope — ETL only; Phase 2 read-API writes don't exist yet).

---

## 2. Locked Decisions (2026-04-15)

| ID | Decision | Rationale |
|:---:|:---|:---|
| **D1** | DQ framework = **pytest + SQL** (plain Python assertion functions + parameterized SQL queries against live Postgres). Great Expectations is **not** adopted. Design doc v2.0 §3.2 / §12 / §14 W3 receive an errata paragraph noting the substitution and the quality KPIs (§14.1 M1 exit, §15) are framework-independent. PR name preserves "Data Quality Gate" with explicit `(pytest + SQL)` subtitle to prevent ambiguity against the roadmap. | GE 1.x carries ~200MB of transitive dependencies, YAML-distributed review surface, slow DataContext init, and active breaking-change churn. Our 5 expectation families reduce to single-line SQL or Python set operations; GE's value-add (pre-built catalog, Data Docs HTML, suite versioning) is not justified at this scale. pytest's test-runner value is preserved for expectation unit tests and CLI contract tests. Reevaluate GE if expectation count exceeds 50 or analyst workflow separates from developer workflow. |
| **D2** | Audit row-level expansion scope = **ETL write path only** (Bootstrap ETL in PR #5/#6). Phase 2 read-API mutation surfaces are explicitly out of scope because that code does not exist yet. | Narrow rollback unit. Prevents PR #7 from becoming a cross-cutting refactor of write instrumentation. Future PRs that introduce new write surfaces (Phase 2 API, PR #8 worker) add their own audit instrumentation following the same schema. |
| **D3** | Row-level audit uses existing `audit_log` schema `(actor, action, entity, entity_id, timestamp, diff_jsonb)` with the following mapping: `actor = "bootstrap_etl"` literal; `action ∈ {"etl_insert","etl_update"}`; `entity` = entity table name (5 tables only: `groups`, `sources`, `codenames`, `reports`, `incidents`); `entity_id` = stringified BIGINT PK; `diff_jsonb` = structured provenance (see D3a). Mapping tables (`report_tags`, `report_codenames`, `incident_sources`, `incident_motivations`, `incident_sectors`, `incident_countries`) are **excluded** from row-level audit because they are derived from entity data and reconstructable from the entity audit trail. Audit writes run inside the caller-owned transaction (`caller_owns_outer` pattern from PR #6 cli.py) so bootstrap rollback cascades to audit. Write strategy: `execute_many` in 500-row batches. | Splits `insert` / `update` so idempotent re-run of the same workbook shows as `etl_update` with empty `changed` — this is the audit trail's proof of idempotency. Entity table exclusion keeps audit write volume ~3× smaller without losing provenance (mapping tables derivable). Same-tx write prevents orphan audit rows on rollback. `execute_many` chunk size sized for pg16 batch insert throughput. |
| **D3a** | `diff_jsonb` shape — row-level: `{"op":"insert","row":{...full row snapshot...},"meta":{...}}` for `etl_insert`; `{"op":"update","changed":{<field>:{"before":X,"after":Y}}|{},"meta":{...}}` for `etl_update`. `meta = {"run_id":<uuid7>, "workbook_sha256":<hex>, "started_at":<iso8601>}`. Empty `changed: {}` on idempotent re-run is the canonical "no-op update" marker. | Provenance is the primary use case (§3.2 "row-level 삽입 이력"), not change-tracking — so full snapshot on insert, field-level diff on genuine updates. `run_id` is uuid7 for timestamp-sortable run correlation across `audit_log` and `dq_events`. `workbook_sha256` makes the audit trail self-describing without an external run registry. |
| **D4** | **Run-level audit events** (new). Schema exception: `entity = "etl_run"` literal, `entity_id = NULL` (permitted by migration 0003), `action ∈ {"etl_run_started","etl_run_completed","etl_run_failed"}`, `diff_jsonb.meta.run_id` **mandatory**. Emitted by `run_bootstrap()` at entry / successful exit / failure exit. Together with row-level events, a single `run_id` SELECT yields the complete run timeline. | Pure row-level audit can't represent run-scoped events (start/end/abort). Reusing `audit_log` with a literal `"etl_run"` entity avoids a second audit table. `entity_id NULL` is already schema-legal post-0003. `run_id` being mandatory here is what binds row-level + run-level + DQ events into a single queryable timeline. |
| **D5** | DQ observations persist to a **new `dq_events` table** (migration 0005). Schema: `(id BIGSERIAL PK, run_id UUID NOT NULL, expectation TEXT NOT NULL, severity TEXT NOT NULL CHECK (severity IN ('warn','error','pass')), observed NUMERIC, threshold NUMERIC, observed_rows BIGINT, detail_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb, observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`. Indexes: `ix_dq_events_run_id`, `ix_dq_events_observed_at DESC`, `ix_dq_events_expectation`. `run_id` shares uuid7 space with `audit_log.diff_jsonb.meta.run_id` so a single run_id joins lineage + quality. Both `pass` and `warn`/`error` outcomes persist so the table is a complete DQ history, not only failures. `audit_log` is **not** used for DQ events — mutation trail and quality trail are semantically separate. | Purpose-built columns enable direct queries for Grafana (future) and daily report aggregation, vs JSONB probing against `audit_log.diff_jsonb`. Independent retention policy (initial: 1 year, vs `audit_log` 2-year §10.6). Keeps `audit_log` semantically pure (mutation tracking) per §9.4 Repudiation. All outcomes (including pass) persisted so trend queries don't need to infer absence. |
| **D6** | DQ runtime = **independent CLI `python -m worker.data_quality`** with two subcommands: `check` (PR #7 implements) and `report` (PR #7 ships interface stub only — no implementation commitment). Expectation functions live in `services/worker/src/worker/data_quality/expectations/*.py` as plain Python functions returning a common `ExpectationResult` dataclass. `check` orchestrates: load expectations → run each against a Postgres connection → persist results to three sinks in a consistent order (stdout ASCII summary, `dq_events` insert, optional JSONL mirror). Structure (2b): expectations are runtime modules in `src/`, not pytest tests. pytest tests verify expectation function correctness and CLI exit-code contract separately (see D6a). | Expectations are runtime logic (run against production PG), not test fixtures — putting them under `tests/` would make them un-invocable outside CI. Common `ExpectationResult` shape is mandatory so the runner and all sinks can treat expectations uniformly. Three-sink guarantee (stdout / DB / optional JSONL) means downstream consumers — CI logs, Grafana, manual review — all see the same data without case-by-case divergence. `report` stub documents the future interface (`--since 1d`) but commits only to argument parsing + "not implemented" exit, so CLI surface is stable without implementation overhead. |
| **D6a** | pytest tests are split into two disjoint suites under `services/worker/tests/data_quality/`: (i) `test_expectations.py` — unit tests per expectation function using seeded fixture data, asserting the function returns the correct `ExpectationResult` for pass/warn/error cases; (ii) `test_cli.py` — CLI contract tests asserting exit codes (0 / 2), stdout summary shape, JSONL mirror format, and `--database-url` requirement (error on missing). No test exercises both layers at once; integration coverage comes from the `data-quality-tests` CI job running `check` against the fixture-seeded live PG. | Splitting test concerns keeps each test file's failure mode diagnostic: expectation unit tests fail when the expectation logic is wrong; CLI contract tests fail when the runner/sinks are wrong. Merging them hides the fault domain and produces the kind of "pytest + runtime logic" blob we rejected in D1. |
| **D7** | DQ data source = **Postgres exclusively**. No sqlite-memory / in-memory DataFrame fallback. `--database-url` is mandatory on the `check` subcommand. CI runs DQ against a `pgvector/pgvector:pg16` service container seeded by running the existing bootstrap fixture pipeline end-to-end. Local development uses a real pg container (docker compose). The PR #6 `--dry-run` sqlite-memory fallback is bootstrap-only and is **not** inherited by DQ. | All 5 expectation families are post-load phenomena (null-rate after defaults apply, dedup across sources, referential integrity against the populated `groups` table, year-range on persisted `published`, value-domain including server defaults like `tlp`). pydantic v2 at PR #5 already covers pre-persist schema checks. sqlite SQL dialect diverges from pg16 on `EXTRACT`, `CHECK` semantics, and NUMERIC coercion — making sqlite fallback actively harmful for DQ correctness. |
| **D8** | Referential integrity expectation — **source of truth = `data/dictionaries/aliases.yml`**. The check loads the YAML canonical set in Python, queries the DB canonical set (e.g. `SELECT DISTINCT canonical_name FROM groups`), and computes `db_set - yaml_set` (forward check) and `yaml_set - db_set` (reverse check). Forward check is **hard error** (severity `error`): any DB canonical not in YAML means normalize leaked or the dictionary is missing an entry the DB already has — both are bugs. Reverse check is **warning only** (severity `warn`): YAML canonicals with no DB occurrence are "unused dictionary entries" — benign. When YAML and DB drift, **YAML wins** and DB is the target of re-normalization. This directional rule is plan-documented so future `aliases.yml` patches + ETL re-runs have an unambiguous recovery path. | normalize step populates DB from YAML (one-way), so DB must always be a subset of YAML. Forward violation = normalize bug (critical). Reverse "violation" = benign (dictionary has unused future entries). Locking direction here prevents false positives and removes ambiguity from the "sprint to add a new group canonical" playbook. |
| **D9** | Failure severity model — two levels only: **`error`** (CLI exits 2, CI red, `dq_events.severity='error'`) and **`warn`** (CLI exits 0, CI green, `dq_events.severity='warn'`). `pass` is a third outcome row written to `dq_events` for trend baselines but is not a severity. `check --fail-on` flag accepts `error` (default), `warn`, `none` for local override. Per-expectation severity mapping finalized in D13. | Mirrors PR #6 bootstrap exit-code policy (0 on no-error / 2 on error) so operators don't learn two different CLI conventions. `pass` rows persisted to enable "DQ pass rate" KPI (§15) computation without inferring from absence. Two-severity keeps the mental model simple; if warn/error splits prove insufficient over time, add `info`/`critical` bands in a later PR. |
| **D10** | **null-rate expectations** = exactly 2 checks, both `warn` severity only. Filter rule: a column qualifies for null-rate checking only if all three hold — (1) DB schema nullable, (2) pydantic does NOT require it (otherwise the check is redundant at 0%), (3) null carries operational meaning (coverage/quality signal, not data-correctness failure). Included: **N1** `codenames.group_id` ratio > 0.50 → warn (alias dictionary coverage signal); **N2** `codenames.named_by_source_id` ratio > 0.50 → warn (source attribution coverage signal). Explicitly excluded (documented in OI1 draft notes): `reports.summary` / `reports.lang` / `reports.reliability` / `reports.credibility` / `sources.country` / `sources.website` / `codenames.first_seen` / `codenames.last_seen` / `groups.mitre_intrusion_set_id` / `groups.color` / `groups.description` — none of these have an active populating pipeline yet, so a null-rate check would always return 100% and carry no signal. | User flagged risk of pydantic-duplication producing meaningless rules. The three-condition filter eliminates that class of waste. PR #7 ships with only 2 null-rate checks rather than a full null-rate sweep — the rest are deferred to PR #9+ after Phase 4 LLM enrichment activates `reports.summary` and Phase 2 read-API provides a metadata curation surface. |
| **D11** | **value-domain expectations** = 4 error checks, each sourced from a code-level constant (no string duplication): **V1** `reports.tlp ∈ TLP_VALUES` where `TLP_VALUES = frozenset({"WHITE","GREEN","AMBER","RED"})` — **new constant** introduced at `services/worker/src/worker/data_quality/constants.py` in PR #7 (no prior code-level TLP constant existed; only the DB `server_default="WHITE"` was present); **V2** `sources.country ∈ ISO3166_ALPHA2_CODES` when NOT NULL; **V3** `incident_countries.country_iso2 ∈ ISO3166_ALPHA2_CODES` (always enforced, PK non-null); **V4** `tags.type ∈ {TAG_TYPE_ACTOR, TAG_TYPE_MALWARE, TAG_TYPE_CVE, TAG_TYPE_OPERATION, TAG_TYPE_SECTOR}` — imported directly from existing `worker.bootstrap.normalize` constants. All four are `error` severity with threshold = 0 violating rows. **V2/V3 source-of-truth constraint:** the private `_ISO3166_ALPHA2_CODES` frozenset in `services/worker/src/worker/bootstrap/schemas.py` is renamed/re-exported to public **`ISO3166_ALPHA2_CODES`**, and the existing `_ISO3166_ALPHA2_CODES` name is retained as a **backward-compat alias** (`_ISO3166_ALPHA2_CODES = ISO3166_ALPHA2_CODES`) so that the module-internal `_is_valid_iso3166_alpha2` continues to work without modification. This keeps the ISO2 list as a single source of truth shared between pydantic ingest validation (PR #5) and DQ post-load checks (PR #7). Deliberately **excluded** (documented in OI2 draft): `sources.type`, `malware.type`, `reports.reliability`, `reports.credibility`, `sources.reliability_default`, `incidents.attribution_confidence`, `incident_motivations.motivation`, `incident_sectors.sector_code` — these have no canonical enum defined in code and would require a DQ-introduced vocabulary, which is out of scope for PR #7. | TLP values fixed at the conventional 4-member set per design doc §9; widening invites domain drift. ISO2 public re-export avoids a parallel 249-code list maintained in DQ (would drift from pydantic over time). Backward-compat alias keeps the PR diff minimal and prevents Codex false-positive flags about "renaming a module-level symbol." tag type enum imported rather than duplicated for the same reason. |
| **D12** | **year-range expectations** = 2 error checks, both hard-bounded at **[2000-01-01, 2030-12-31]**: **Y1** `reports.published` year ∈ bounds (required field, always enforced); **Y2** `incidents.reported` year ∈ bounds when NOT NULL. Both are `error` severity with threshold = 0 violating rows. Lower bound 2000 chosen because known DPRK APT public reporting starts in the early 2000s (Lazarus attribution ~2009+, earlier Guardians of Peace style operations). Upper bound 2030 provides ~5 years of forward buffer from current 2026-04-15 to absorb near-future-dated reports while catching typos outside that window. Explicitly **excluded** (OI3 draft): `vulnerabilities.published` (CVE-ID embedded year cross-check is a separate referential check deferred to PR #8+), `codenames.first_seen` / `last_seen` (vendor reporting timing is an exogenous variable with no principled bound), `geopolitical_events.date` (data surface not yet active in PR #7 scope). | Range chosen to be wide enough that any violation is a parsing bug or workbook typo (correctness issue, hence `error`), not a statistical distribution tail. pydantic validates date format but not range, so D12 is a complement, not duplication. If Phase 4 forecasting produces forward-dated records that land in `reports`, upper bound must be revisited or dropped at that time — documented as a future review trigger. |
| **D13** | **Per-expectation severity mapping** — PR #7 ships **11 expectations total**: 7 `error` (value-domain 4 + year-range 2 + referential forward 1) and 4 `warn` (null-rate 2 + referential reverse 1 + dedup-rate 1). Complete registry in §4 Task Breakdown Group D. D9's 2-level severity model (`warn` / `error`, with `pass` as a non-severity outcome row) is **verified** against the full 11-item mapping — no expectation introduces a third band, no expectation implies a new sink, no expectation requires a framework feature beyond what D6/D6a establish. | Consolidating the severity map into a single locked decision lets Codex (and future contributors) verify D9 compliance by reading one table instead of re-deriving it from scattered expectation files. Verification is a plan-time guarantee, not a test-time check — the 11-item table is the contract. |

---

## 3. Scope

### In scope
- `db/migrations/versions/0005_dq_events.py` — create `dq_events` table per D5 schema
- `services/worker/src/worker/data_quality/` package:
  - `__init__.py`, `__main__.py` (CLI hook `python -m worker.data_quality`)
  - `constants.py` — **new**: `TLP_VALUES = frozenset({"WHITE","GREEN","AMBER","RED"})` per D11/V1. Single-file home for DQ-owned constants so future additions have an obvious landing spot.
  - `results.py` — `ExpectationResult` frozen dataclass, severity enum, sink protocols
  - `runner.py` — load expectations, execute against PG connection, fan out to sinks
  - `expectations/__init__.py` — registry (11-item)
  - `expectations/null_rate.py` — D10 N1, N2 (codenames.group_id, codenames.named_by_source_id null ratio, warn at > 0.50)
  - `expectations/value_domain.py` — D11 V1–V4 (reports.tlp, sources.country, incident_countries.country_iso2, tags.type), all `error`
  - `expectations/referential_integrity.py` — D8 forward (`error`) + reverse (`warn`) against `aliases.yml` loaded via `worker.bootstrap.aliases.AliasDictionary`
  - `expectations/year_range.py` — D12 Y1, Y2 (reports.published, incidents.reported), bounds 2000-01-01 – 2030-12-31, `error`
  - `expectations/dedup_rate.py` — `url_canonical` distinct ratio, initial 15% warn threshold, always `warn` severity per earlier discuss-phase
  - `sinks/stdout.py` — ASCII summary table writer
  - `sinks/db.py` — `dq_events` batch insert
  - `sinks/jsonl.py` — optional mirror writer
  - `cli.py` — argparse for `check` / `report`, `--database-url`, `--run-id`, `--workbook-sha256`, `--report-path`, `--fail-on`
- `services/worker/src/worker/bootstrap/schemas.py` — **modify**: rename private `_ISO3166_ALPHA2_CODES` to public `ISO3166_ALPHA2_CODES` and add `_ISO3166_ALPHA2_CODES = ISO3166_ALPHA2_CODES` backward-compat alias per D11. Update `__all__` to export the public name. No change to the existing `_is_valid_iso3166_alpha2` helper or `IncidentRow` validator. Unit tests under `services/worker/tests/unit/test_schemas.py` get a single new assertion that both names resolve to the same frozenset identity.
- `services/worker/src/worker/bootstrap/` extensions (audit wiring):
  - `audit.py` — new module: `write_row_audit()`, `write_run_audit()`, shared `AuditMeta` builder
  - `upsert.py` — call `write_row_audit` after each successful entity upsert, inside the caller tx
  - `cli.py` — emit `etl_run_started` at entry, `etl_run_completed` on success, `etl_run_failed` on exception; generate and propagate uuid7 `run_id` + workbook sha256
- `services/worker/tests/data_quality/` package:
  - `conftest.py` — pg16 fixture session (testcontainers or reuse CI service), bootstrap-seeded schema
  - `test_expectations.py` — unit tests per expectation (happy / warn / error paths with seeded pollution)
  - `test_cli.py` — CLI exit code contract, stdout format, JSONL mirror format, `--database-url` required error
- `services/worker/tests/unit/test_audit.py` — unit tests for new `worker.bootstrap.audit` module (row-level + run-level writers, tx rollback cascade, `diff_jsonb` shape validation)
- `services/worker/tests/integration/test_bootstrap_audit.py` — integration test: run `run_bootstrap` against the fixture and assert `audit_log` has (a) one `etl_run_started` + one `etl_run_completed` per run, (b) `etl_insert` rows for every entity row on first run, (c) `etl_update` with empty `changed` on idempotent second run, (d) rollback cascades on forced failure
- `.github/workflows/ci.yml` — new `data-quality-tests` job with `pgvector/pgvector:pg16` service container, bootstrap-seeds the fixture, then runs the DQ CLI `check` + the pytest suites
- `services/worker/pyproject.toml` — add `uuid6` (for uuid7) as runtime dep if stdlib alternative not acceptable; no other new deps
- `docs/DPRK_Cyber_Threat_Dashboard_설계서_v2.0.md` — errata paragraph after §3.2 clarifying pytest + SQL substitution (D1)

### Out of scope (explicit)
- Great Expectations framework — D1
- In-memory / sqlite DQ fallback — D7
- Pre-ingest DQ checks for RSS/TAXII — PR #8
- Grafana board for DQ trend — Phase 3+ observability
- `report` subcommand implementation beyond argparse stub — D6
- Daily report email / webhook / Slack — TBD, post Phase 3
- Audit row-level for non-ETL write paths — D2
- Mapping-table row-level audit — D3
- LLM quality heuristics — Phase 4
- Frontend — Phase 2+
- `dq_events` retention policy enforcement automation (manual policy documented, no cron) — post PR #7

---

## 4. Task Breakdown

Dependency order. Tasks within the same group can be parallelized during implementation.

**Group A — Schema and data model**
- **T1**: Migration 0005 `dq_events` table + indexes. Reversible (downgrade drops table). Round-trip verified locally against `pgvector/pgvector:pg16`.
- **T2**: `db/migrations/tests/test_0005_dq_events.py` — migration reversibility test (upgrade → downgrade → upgrade, schema identical)

**Group B — Audit wiring (extends PR #5/#6 code)**
- **T3**: `worker.bootstrap.audit` module — `write_row_audit`, `write_run_audit`, `AuditMeta` (run_id, workbook_sha256, started_at). `execute_many` 500-row chunking.
- **T4**: `worker.bootstrap.upsert` integration — call `write_row_audit` after each entity upsert. Ensure same-tx guarantee under `caller_owns_outer`.
- **T5**: `worker.bootstrap.cli` integration — generate uuid7 run_id at entry, compute workbook sha256 from loaded bytes, emit `etl_run_started` / `etl_run_completed` / `etl_run_failed`.
- **T6**: Unit tests (`tests/unit/test_audit.py`) — row-level shape, run-level shape, meta builder, 500-row batch.
- **T7**: Integration tests (`tests/integration/test_bootstrap_audit.py`) — full run verifies audit_log row counts, action distribution, idempotent re-run empty `changed`, forced-failure rollback cascade.

**Group C — DQ runtime skeleton**
- **T8**: `worker.data_quality.results` — `ExpectationResult` frozen dataclass (`name: str, severity: Literal["pass","warn","error"], observed: Decimal|None, threshold: Decimal|None, observed_rows: int|None, detail: dict`), severity enum, `Sink` Protocol.
- **T9**: `worker.data_quality.runner` — `run_expectations(conn, run_id, expectations) -> list[ExpectationResult]`, fan-out to configured sinks in order (stdout → db → jsonl optional).
- **T10**: `worker.data_quality.sinks.{stdout,db,jsonl}` — three sink implementations conforming to `Sink` Protocol.

**Group D — Expectation functions** (11 total, locked per D10–D13)

- **T11**: `expectations.referential_integrity` — D8 forward (`error`) + reverse (`warn`). YAML loader reused from PR #5 `aliases.py` (`AliasDictionary.load_from_file`). 2 expectations: `groups.canonical_name.forward_check`, `groups.canonical_name.reverse_check`.
- **T12**: `expectations.dedup_rate` — 1 expectation: `reports.url_canonical.dedup_rate` — `1 - COUNT(DISTINCT url_canonical) / COUNT(*)`, warn at ratio > 0.15 (initial). Always `warn`.
- **T13**: `expectations.null_rate` — D10. 2 expectations: `codenames.group_id.null_rate`, `codenames.named_by_source_id.null_rate`. Both warn at ratio > 0.50.
- **T14**: `expectations.value_domain` — D11/V1–V4. 4 expectations: `reports.tlp.value_domain` (imports `worker.data_quality.constants.TLP_VALUES`), `sources.country.iso2_conformance` + `incident_countries.country_iso2.iso2_conformance` (both import `worker.bootstrap.schemas.ISO3166_ALPHA2_CODES`), `tags.type.enum_conformance` (imports `worker.bootstrap.normalize.TAG_TYPE_*`). All `error` at 0 violating rows.
- **T15**: `expectations.year_range` — D12/Y1, Y2. 2 expectations: `reports.published.year_range`, `incidents.reported.year_range`. Both bounded `[2000-01-01, 2030-12-31]`, `error` at 0 violating rows. Y2 excludes NULL rows from the count (NULL is a separate coverage concern, not a range concern).
- **T15a**: `worker.data_quality.constants` module — per D11, introduces `TLP_VALUES` frozenset. First and only constant in PR #7.
- **T15b**: `worker.bootstrap.schemas` edit — per D11 backward-compat rule, add public `ISO3166_ALPHA2_CODES`, retain private `_ISO3166_ALPHA2_CODES` as alias, extend `__all__`. One new assertion in `tests/unit/test_schemas.py`: `assert schemas._ISO3166_ALPHA2_CODES is schemas.ISO3166_ALPHA2_CODES`.

**Group E — CLI and tests**
- **T16**: `worker.data_quality.cli` — argparse for `check` (`--database-url` required, `--run-id`, `--workbook-sha256`, `--report-path`, `--fail-on {error,warn,none}`) + `report` stub (`--since`, prints "not implemented in PR #7" and exits 3). `__main__.py` wires subcommands.
- **T17**: `tests/data_quality/test_expectations.py` — unit test per expectation function with seeded fixture pollution for each severity path.
- **T18**: `tests/data_quality/test_cli.py` — exit code matrix (0 on clean + warn-only, 2 on any error with default `--fail-on error`), missing `--database-url` error, stdout summary shape assertion, JSONL mirror row shape.

**Group F — CI and docs**
- **T19**: `.github/workflows/ci.yml` — new `data-quality-tests` job. Service container `pgvector/pgvector:pg16-v0.7.0`. Steps: checkout → uv sync → alembic upgrade head → bootstrap seed (`python -m worker.bootstrap --workbook tests/fixtures/bootstrap_sample.xlsx --database-url $DATABASE_URL`) → DQ check (`python -m worker.data_quality check --database-url $DATABASE_URL --fail-on error --report-path artifacts/dq_report.jsonl`) → pytest (`tests/data_quality/`) → upload-artifact JSONL mirror.
- **T20**: Design doc v2.0 errata — insert a short paragraph after §3.2's existing GE bullet noting D1 substitution and quoting this plan as the implementing decision record.
- **T21**: `services/worker/README.md` — document DQ CLI invocation, exit code meaning, `dq_events` query examples, `--fail-on` override.

---

## 5. Risks

| ID | Risk | Impact | Mitigation |
|:---:|:---|:---|:---|
| **R1** | CI wall-time regression from new `data-quality-tests` job (new pg16 container + bootstrap seed + DQ run ~40s) | CI parallelism may still hide this, but sequential critical path grows | Run the new job in parallel with `worker-tests`; fail fast on any-job red. Monitor total wall time; if > +60s sustained, reduce expectation scope or share pg container with `db-migrations` job. |
| **R2** | uuid7 library — Python stdlib `uuid` does not yet expose uuid7. Using `uuid6` PyPI package adds a dep. | Small new transitive (`uuid6` has no deps). Acceptable. | If user rejects the new dep, generate uuid7 inline (~15 LOC) per RFC 9562 and unit-test the bit layout. |
| **R3** | Audit write volume doubles bootstrap total writes (~2,400 entities → ~4,800 total including audit rows) | Bootstrap is one-shot, runs in seconds. Not a production hot path. | Chunk size 500 in `execute_many`. Integration test asserts bootstrap wall time stays within 2× the PR #6 baseline. |
| **R4** | `diff_jsonb` full-row snapshot on insert makes `audit_log` grow faster than previously planned | Storage — pg16 JSONB compression handles this well; 2,400 rows × ~500B JSON = ~1.2 MB per bootstrap run. Acceptable. | Document in §10.6 that audit_log sizing assumption now includes ETL row-level. |
| **R5** | pytest CLI contract tests may flake against real pg container startup timing | Flake risk on CI | Use healthcheck wait in service container (`pg_isready`). Already standard in PR #4 `db-migrations` job; copy that pattern. |
| **R6** | User draft of null-rate / value-domain / year-range thresholds may conflict with D1–D9 locked decisions | Scope creep if thresholds imply a new severity band or a new sink | Review step explicitly listed (§7 Open Items) before marking plan Locked. |
| **R7** | `aliases.yml` forward check fails on production data because normalize let an unknown name through | This is the failure this check exists to catch — by design | Document in runbook: D8 forward failure → inspect `dq_events.detail_jsonb` for offending names → update `aliases.yml` → re-run bootstrap. |
| **R8** | Codex reviewer may rate-limit mid-review again (observed on PR #5 round 7) | Extra review rounds may need manual fallback | User already has fallback review process documented in memory (`feedback_codex_iteration.md`). Apply same pattern if needed. |

---

## 6. Acceptance Criteria

PR #7 is mergeable when:

1. Migration 0005 up/down round-trip passes on `pgvector/pgvector:pg16` locally and in CI `db-migrations` job.
2. `python -m worker.data_quality check --database-url <pg> --fail-on error` exits 0 on the fixture (no error-severity events expected on clean fixture).
3. `python -m worker.data_quality check --database-url <pg> --fail-on warn` exits 2 on the fixture (dedup-rate at 15% initial threshold may emit a warn event; see user draft for exact thresholds).
4. `dq_events` contains one row per expectation per run with correct `run_id` propagation.
5. `audit_log` contains, for a fixture bootstrap run: exactly 1 `etl_run_started` + 1 `etl_run_completed` + N × `etl_insert` (N = fixture entity count) + 0 `etl_update` on first run.
6. Idempotent second run of bootstrap on the same fixture produces only `etl_update` with empty `changed`.
7. Forced failure (e.g. inject an error in upsert loop) produces 1 `etl_run_failed` and zero leaked `etl_insert` rows (same-tx rollback proof).
8. `worker-tests` CI job remains green (audit wiring does not regress PR #6 tests).
9. New `data-quality-tests` CI job green on the merge commit. Wall time < 60s.
10. pytest coverage: `services/worker/src/worker/data_quality/` ≥ 85%; `services/worker/src/worker/bootstrap/audit.py` ≥ 90%.
11. Codex review clean (expected 2–5 rounds per `feedback_codex_iteration.md`).
12. Design doc v2.0 §3.2 errata paragraph merged in the same PR.

---

## 7. Open Items Resolution Log

All OI1–OI4 items from discuss-phase round 1 are **closed as of 2026-04-15** and locked as D10–D13. Draft was Claude-authored per user delegation ("드래프트 작성") then reviewed against the §7.1 validation checklist and confirmed against D1–D9 for conflict. User approved the draft with one constraint (V2/V3 backward-compat alias) which was folded into D11.

| OI | Resolution | Locked as | Note |
|:---:|:---|:---:|:---|
| **OI1** | null-rate reduced to 2 warn-only checks via 3-condition filter (nullable ∧ not-pydantic-required ∧ operational-signal) | **D10** | PR #9+ reopens scope after Phase 4 LLM activates more populated columns |
| **OI2** | value-domain = 4 error checks, all sourced from code-level constants; TLP_VALUES introduced, ISO3166 re-exported public with alias | **D11** | `sources.type` / `malware.type` / Admiralty code fields deferred — no canonical enum in code |
| **OI3** | year-range = 2 error checks bounded [2000-01-01, 2030-12-31]; reports.published + incidents.reported | **D12** | vulnerabilities.published CVE-year cross-check deferred to PR #8+ |
| **OI4** | per-expectation severity = 7 error + 4 warn (11 total); single master table in D13 and §4 Group D | **D13** | D9 2-level compliance verified — see §7.2 below |

### 7.1 Validation Checklist Results (executed 2026-04-15)

| # | Check | Result | Detail |
|:---:|:---|:---:|:---|
| 1 | Every expectation has a defined severity | ✅ | 11/11 explicit (7 error + 4 warn) |
| 2 | Every threshold has a concrete numeric value | ✅ | 0 / 0.15 / 0.50 / date bounds, no vague language |
| 3 | No threshold implies a new severity band beyond `warn`/`error`/`pass` | ✅ | See §7.2 |
| 4 | No threshold implies a new sink beyond stdout/db/jsonl | ✅ | All 11 go through D6 3-sink fan-out |
| 5 | `reports.tlp` value-domain set matches PR #5 pydantic schema's constant | ⚠ resolved | No prior constant existed; D11/V1 creates `worker.data_quality.constants.TLP_VALUES` as the canonical source |
| 6 | ISO 3166-1 alpha-2 list matches PR #5 `schemas.py` vendored set | ⚠ resolved in plan | `_ISO3166_ALPHA2_CODES` (private) to be renamed to public `ISO3166_ALPHA2_CODES` with backward-compat alias per D11 and T15b — this is a planned modification, not yet applied to the tree. Single frozenset identity to be preserved across pydantic ingest and DQ post-load layers. |
| 7 | year-range lower bound ≥ 2000 | ✅ | 2000-01-01 per D12, design doc §3.2 implicit baseline |
| 8 | Every hard-fail threshold has a runbook pointer | ⚠ partial | PR #7 adds a minimal "Runbook" section to `services/worker/README.md` covering the 7 error-severity expectations (dedicated per-expectation playbooks deferred to post-merge smoke run per §8 step 9). Marker `TBD: runbook` acceptable for expectations where first real-data failure mode is still unknown. |

### 7.2 D9 2-Level Severity Compliance Verification

Per the user's explicit follow-up request ("다음 검토에서는 11개 severity 매핑표가 실제로 D9의 2-level 모델만 쓰는지만 확인하면 충분"), the full registry is enumerated here with severity assignment:

| # | Expectation | Severity | Sink path | D9 compliant |
|:---:|:---|:---:|:---|:---:|
| 1 | `reports.tlp.value_domain` | error | stdout+db+jsonl | ✅ |
| 2 | `sources.country.iso2_conformance` | error | stdout+db+jsonl | ✅ |
| 3 | `incident_countries.country_iso2.iso2_conformance` | error | stdout+db+jsonl | ✅ |
| 4 | `tags.type.enum_conformance` | error | stdout+db+jsonl | ✅ |
| 5 | `reports.published.year_range` | error | stdout+db+jsonl | ✅ |
| 6 | `incidents.reported.year_range` | error | stdout+db+jsonl | ✅ |
| 7 | `groups.canonical_name.forward_check` | error | stdout+db+jsonl | ✅ |
| 8 | `groups.canonical_name.reverse_check` | warn | stdout+db+jsonl | ✅ |
| 9 | `reports.url_canonical.dedup_rate` | warn | stdout+db+jsonl | ✅ |
| 10 | `codenames.group_id.null_rate` | warn | stdout+db+jsonl | ✅ |
| 11 | `codenames.named_by_source_id.null_rate` | warn | stdout+db+jsonl | ✅ |

**Compliance summary**: 11/11 expectations use exclusively `error` or `warn`. Zero expectations introduce a third band. Zero expectations bypass the D6 three-sink fan-out. `pass` outcome rows are written to `dq_events` for trend baselines per D5 but are not an expectation-level severity assignment — they are the non-violation runtime result. **D9 2-level model verified.**

---

## 8. Rollout Plan

Per the PR #4/#5/#6 pattern established in memory:

1. **Plan lock** — this document + OI1–OI4 user draft + my validation → mark Locked.
2. **Branch** — `feat/p1.2-data-quality` off `main`.
3. **First commit** — the locked plan doc (this file) so the rollback unit is trivial.
4. **Implementation** — Groups A → B → C → D → E → F in order. B and C can parallelize; D depends on user draft merge.
5. **Self-review** — run `uv run pytest services/worker/tests/` + new job locally before pushing.
6. **Codex review** — `codex review --base main --title "..."`. Expect 2–5 rounds.
7. **User manual review** — if Codex rate-limits mid-review (see R8), fallback to manual review per `feedback_codex_iteration.md`.
8. **Merge** — squash + delete branch. Verify all 7 CI jobs (including new `data-quality-tests`) green on merge commit.
9. **Post-merge smoke** — run `python -m worker.data_quality check` against a local pg container with real workbook (if staged) to verify thresholds are sane in practice. Capture any divergence and open follow-up for threshold retuning.

---

## 9. References

- Design doc v2.0: §3.2 (Bootstrap ETL + DQ + lineage), §9.4 (Repudiation / audit), §10.6 (retention), §12 (test strategy), §14 W3 (Phase 1 roadmap), §14.1 (M1 exit), §15 (KPIs)
- PR #4 plan: `db/migrations/versions/0004_bigint_pk_migration.py` — migration pattern
- PR #5 plan: `docs/plans/pr5-bootstrap-etl.md` — template format this document follows
- PR #5 implementation: `services/worker/src/worker/bootstrap/upsert.py` (entry point for audit wiring), `services/worker/src/worker/bootstrap/aliases.py` (D8 YAML loader reuse)
- PR #6 implementation: `services/worker/src/worker/bootstrap/cli.py` (`caller_owns_outer` pattern, exit code policy to mirror), `services/worker/src/worker/bootstrap/errors.py` (ASCII-only summary pattern)
- Memory: `feedback_codex_iteration.md`, `pitfall_pytest_rootdir.md`, `review_discipline.md`

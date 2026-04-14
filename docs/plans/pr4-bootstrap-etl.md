# PR #4 Plan — Bootstrap ETL + Alias Dictionary

**Phase:** 1.4 (design doc v2.0 §14 roadmap — resequenced ahead of 1.3 per dependency order)
**Status:** Locked 2026-04-14. Changes require an explicit scope-change note in the implementing PR description.
**Predecessors:** PR #1 (Phase 0 scaffold), PR #2 (P1.1 OIDC/RBAC), PR #3 (CI pytest gate)
**Successors:** PR #5 (Great Expectations + audit row-level), PR #6 (RSS/TAXII worker + Prefect)

---

## 1. Goal

Load the v1.0 workbook (Actors / Reports / Incidents — ~2,372 rows total) into the existing Phase 0 schema as **canonical, deduplicated, idempotent data** so downstream API read paths, data-quality checks (PR #5), and analytics views (Phase 3+) have a real corpus to operate on.

Non-goal: any data-quality framework, any audit-log row-level expansion, any RSS/TAXII ingest, any Prefect orchestration, any frontend change.

---

## 2. Locked Decisions (2026-04-14)

| ID | Decision | Rationale |
|:---:|:---|:---|
| **D1** | Workbook source = `(a)+(b)` dual. Real workbook loaded from `$BOOTSTRAP_WORKBOOK_PATH` (git-ignored). Repo commits a **synthetic 10–20 row fixture workbook** under `services/worker/tests/fixtures/bootstrap_sample.xlsx` for CI and unit tests. | Keeps licensed / large data out of git; CI is deterministic; local dev reproduces real flow with one env var. |
| **D2** | Great Expectations and audit-log row-level expansion are **out of scope** for PR #4. They land in PR #5. | Splits rollback units. PR #4 is already wide (input parsing, normalization, upsert, CLI). GE adds a full new dependency + fixtures footprint that should not block ETL landing. |
| **D3** | CLI-first: `python -m worker.bootstrap --workbook <path> [--dry-run] [--limit N]`. No Prefect flow in PR #4. | Bootstrap is one-shot. Prefect orchestration is only justified when RSS/TAXII scheduling arrives in PR #6. |
| **D4** | BigInt PK migration is a **separate preflight PR** (working name: PR #4a / `feat/p1.x-bigint-pk`) landing before PR #4 implementation starts. | Tables are empty right now — ALTER is cheap. Bundling with ETL makes the rollback unit too large. |
| **D5** | Row-level failures write to `artifacts/bootstrap_errors.jsonl`. Exit code rule: **fail=0 → 0**, **0<fail_rate≤5% → 0 with warning summary**, **fail_rate>5% → non-zero exit (2)**. | 2,000+ rows will have noise; a single bad row should not halt ingest, but quality regressions must break CI. 5% threshold derived from design doc §3.2 data-quality envelope. |

---

## 3. Scope

### In scope (PR #4)
- `data/dictionaries/aliases.yml` — versioned YAML alias dictionary (groups, malware, CVE, campaigns)
- `services/worker/src/worker/bootstrap/` package:
  - `loader.py` — openpyxl + pandas sheet loader
  - `schemas.py` — pydantic v2 input row schemas (Actor, Report, Incident)
  - `normalize.py` — URL canonicalization + `sha256_title` + tag regex classifier (5 types: actor/malware/cve/operation/sector) + alias-dictionary apply
  - `upsert.py` — repository-pattern upserts for `groups`, `codenames`, `sources`, `reports`, `tags`, `report_tags`, `incidents`, incident-mapping tables
  - `cli.py` — `python -m worker.bootstrap` entrypoint
  - `errors.py` — JSONL dead-letter writer + exit-code policy
- `services/worker/tests/fixtures/bootstrap_sample.xlsx` — synthetic fixture (10–20 rows per sheet covering: happy path, duplicate URL, unknown group alias, malformed tag, missing required field)
- `services/worker/tests/unit/` — loader, normalize, upsert (sqlite or testcontainers Postgres), CLI exit-code policy
- `services/worker/pyproject.toml` — add `openpyxl`, `pandas`, `pydantic>=2`, `pyyaml`, `sqlalchemy`, `psycopg[binary]`, dev deps: `pytest`, `pytest-cov`
- `.github/workflows/ci.yml` — extend `python-services (worker)` job (or add new `worker-tests` job) with pytest + coverage gate + bootstrap dry-run against the fixture

### Out of scope (explicit)
- Great Expectations suite → PR #5
- Audit-log row-level insert for bootstrap → PR #5
- Prefect flow registration → PR #6
- RSS/TAXII worker → PR #6
- BigInt PK migration → PR #4a (preflight)
- Frontend changes → Phase 2+
- Incident-to-CVE auto-linking heuristics → Phase 3
- LLM enrichment of tags → Phase 4

---

## 4. Task Breakdown

Dependency order. T1 lands in the preflight PR (#4a); T2–T9 land in PR #4.

| # | Task | Depends on | Est. | Exit criteria |
|:---:|:---|:---|:---:|:---|
| **T1** | BigInt PK migration (preflight PR #4a). `0004_bigint_pk_migration.py` — ALTER all Integer PK/FK columns (`groups`, `codenames`, `sources`, `reports`, `tags`, `report_tags`, `incidents`, `techniques`, `malware`, `vulnerabilities`, + staging FKs). | PR #3 merged | 0.5d | `alembic upgrade head` + `downgrade -1` + `upgrade head` green in CI; no Integer PKs remain in schema dump |
| T2 | `aliases.yml` + YAML loader | T1 | 0.5d | Loader returns `dict[canonical, set[alias]]`; round-trip YAML test |
| T3 | Pydantic row schemas (Actor / Report / Incident) | T1 | 0.5d | Schemas reject the 5 failure rows in the fixture; accept the happy rows |
| T4 | URL canonicalize + `sha256_title` util | T1 | 0.25d | Unit tests for tracking-param strip, casing, trailing slash, IDN, hash determinism |
| T5 | Tag regex 5-type classifier + alias apply | T2, T4 | 0.5d | Covers every tag pattern in design doc §2.3; falls back to `unknown_type` safely |
| T6 | Upsert repositories | T3, T5 | 1d | `url_canonical` unique constraint drives idempotency; re-running the fixture load produces zero duplicates |
| T7 | CLI entrypoint + dead-letter + exit-code policy | T6 | 0.5d | `--workbook`, `--dry-run`, `--limit`; the 3 exit-code branches from D5 are covered by tests |
| T8 | Unit tests (loader, normalize, upsert, CLI) | T3–T7 | 1d | Worker coverage ≥70% (mirror PR #3 gate); fixture-driven; no real DB needed beyond sqlite-memory for upsert smoke |
| T9 | CI extension: worker pytest job + bootstrap dry-run step using fixture | T8 | 0.25d | `worker-tests` job green on PR; fixture dry-run exits 0 with `fail_rate=0` |

**Total estimate:** ~5 dev-days for PR #4, plus ~0.5d for PR #4a preflight.

---

## 5. Risks & Mitigations

| Risk | Severity | Mitigation |
|:---|:---:|:---|
| Real workbook column names differ from v1.0 assumption | High | Build against fixture first; real workbook is exercised only via local `BOOTSTRAP_WORKBOOK_PATH`; column mapping is a config constant, not hardcoded in parsers. |
| URL canonicalization loses signal (two semantically different URLs collapse to same canonical) | High | Canonicalization keeps path + significant query params; strip rules are whitelisted (`utm_*`, `fbclid`, `gclid`) rather than blacklisted. Unit tests include adversarial cases. |
| Alias dictionary entry conflicts (same alias maps to two canonicals) | Med | Loader validates bijection at load time and fails fast with a dictionary-lint error; this is checked by a unit test. |
| `tags` regex classifier over-matches (e.g. `#operation` captures `#op`) | Med | Regex ordered by specificity; `unknown_type` fallback keeps the raw tag for later LLM cleanup rather than silently dropping. |
| >5% fail rate triggers on fixture | Med | Fixture is synthetic and controlled; failure-path rows are tagged so the test asserts `fail_rate ≤ 5%` holds on happy fixture and `> 5%` holds on a stress fixture. |
| BigInt migration (T1) breaks existing `services/api` SQLAlchemy models | Med | PR #4a must also update `services/api` model column types where present; CI `api-tests` job is the gate. |

---

## 6. Rollback Plan

- **PR #4a (BigInt)**: Alembic `downgrade -1` reverses. No data loss because tables are empty today. Verified by CI `db-migrations` job.
- **PR #4**: Pure additive (new package under `services/worker`, new YAML under `data/`, new CI job). Revert = `git revert`. Running `worker.bootstrap` against prod DB is manual and gated by operator, so revert leaves the DB untouched.

---

## 7. Acceptance Criteria

PR #4 is mergeable only when all of the following hold:

1. Preflight PR #4a is merged to main.
2. `python -m worker.bootstrap --workbook services/worker/tests/fixtures/bootstrap_sample.xlsx --dry-run` exits 0 against a clean schema.
3. Re-running the same command non-dry against sqlite-memory produces the expected row counts in every target table, and a second run produces zero new rows (idempotency proven).
4. Worker pytest coverage ≥70% (matching PR #3 baseline).
5. `artifacts/bootstrap_errors.jsonl` is created only when there are failures; its schema is documented in `services/worker/README.md`.
6. `alembic upgrade head` + `downgrade -1` + `upgrade head` still green.
7. All existing CI jobs from PR #3 still green.
8. Final external review reports no unresolved critical/high findings.

---

## 8. Open Questions

- **Workbook delivery path**: the real v1.0 workbook is not yet staged on this dev box. Blocker for local end-to-end verification against real data before merge. Mitigation: PR #4 CI uses the fixture; real-data smoke happens locally post-merge, with a follow-up issue if column drift is detected.
- **Sectors / countries reference tables**: the 0001 migration defines `incidents` but the mapping tables (`incident_sectors`, `incident_countries`, `incident_motivations`) need to be re-read to confirm naming and FK direction before T6 starts. Not a decision — a read-before-code checkpoint.

---

## 9. Change Log

- **2026-04-14** — Plan locked. D1–D5 confirmed. Task order T1→T9 set. Acceptance criteria fixed.

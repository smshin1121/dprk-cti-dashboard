# PR #5 & #6 Plan — Bootstrap ETL + Alias Dictionary

**Phase:** 1.4 (design doc v2.0 §14 roadmap — resequenced ahead of 1.3 per dependency order)
**Status:** Locked 2026-04-14. PR split updated 2026-04-15. Changes require an explicit scope-change note in the implementing PR description.
**Predecessors:** PR #1 (Phase 0 scaffold), PR #2 (P1.1 OIDC/RBAC), PR #3 (CI pytest gate), PR #4 (BigInt PK preflight — merged 2026-04-15)
**Successors:** PR #7 (Great Expectations + audit row-level), PR #8 (RSS/TAXII worker + Prefect)

---

## 1. Goal

Load the v1.0 workbook (Actors / Reports / Incidents — ~2,372 rows total) into the existing Phase 0 schema as **canonical, deduplicated, idempotent data** so downstream API read paths, data-quality checks (PR #7), and analytics views (Phase 3+) have a real corpus to operate on.

Non-goal: any data-quality framework, any audit-log row-level expansion, any RSS/TAXII ingest, any Prefect orchestration, any frontend change.

---

## 2. Locked Decisions (2026-04-14)

| ID | Decision | Rationale |
|:---:|:---|:---|
| **D1** | Workbook source = `(a)+(b)` dual. Real workbook loaded from `$BOOTSTRAP_WORKBOOK_PATH` (git-ignored). Repo commits a **synthetic 10–20 row fixture workbook** under `services/worker/tests/fixtures/bootstrap_sample.xlsx`, generated from a versioned YAML source-of-truth by `scripts/generate_bootstrap_fixture.py` so the fixture is reproducible rather than a hand-edited binary. CI and unit tests use only the fixture. | Keeps licensed / large data out of git; CI is deterministic; local dev reproduces real flow with one env var; fixture edits remain reviewable as YAML diffs. |
| **D2** | Great Expectations and audit-log row-level expansion are **out of scope** for PR #5/#6. They land in PR #7. | Splits rollback units. Bootstrap ETL is already wide (input parsing, normalization, upsert, CLI). GE adds a full new dependency + fixtures footprint that should not block ETL landing. |
| **D3** | CLI-first: `python -m worker.bootstrap --workbook <path> [--dry-run] [--limit N]`. No Prefect flow in PR #5/#6. | Bootstrap is one-shot. Prefect orchestration is only justified when RSS/TAXII scheduling arrives in PR #8. |
| **D4** | BigInt PK migration landed as the preflight PR #4 on 2026-04-15. Tables were empty so the ALTER was cheap and its rollback unit stayed small. | See 0004_bigint_pk_migration.py. |
| **D5** | Row-level failures write to `artifacts/bootstrap_errors.jsonl`. Exit code rule: **fail=0 → 0**, **0<fail_rate≤5% → 0 with warning summary**, **fail_rate>5% → non-zero exit (2)**. | 2,000+ rows will have noise; a single bad row should not halt ingest, but quality regressions must break CI. 5% threshold derived from design doc §3.2 data-quality envelope. |

---

## 3. PR Split (added 2026-04-15)

The original plan kept T2–T9 in a single PR #5. Splitting it into two PRs keeps each review focused on one concern: **what the data *looks like* after normalization** vs **how the operator *drives* the load**.

| PR | Scope | Tasks | Rationale |
|:---:|:---|:---|:---|
| **PR #5** | Normalization + upsert — "the data shape" | T2–T6 | alias dict, pydantic schemas, URL canonicalization, tag classifier, upsert repositories. Pure library code — no CLI, no exit-code policy. Unit tests for this PR exercise the library against the fixture. |
| **PR #6** | CLI + dead-letter + CI — "the operator interface" | T7–T9 | `python -m worker.bootstrap` entrypoint, JSONL dead-letter, exit-code policy (fail-rate branching), CI `worker-tests` job, fixture dry-run step. Depends on PR #5 library being on main. |

**Shared fixture infrastructure lands in PR #5** (with the normalization code it serves). PR #6 reuses the same fixture without regenerating it.

---

## 4. Scope

### In scope — PR #5 (T2–T6)
- `scripts/generate_bootstrap_fixture.py` — deterministic openpyxl generator
- `services/worker/tests/fixtures/bootstrap_sample.yaml` — YAML source-of-truth for the fixture (happy + failure rows)
- `services/worker/tests/fixtures/bootstrap_sample.xlsx` — generated workbook committed for CI reproducibility
- `data/dictionaries/aliases.yml` — versioned YAML alias dictionary (groups, malware, CVE, campaigns)
- `services/worker/src/worker/bootstrap/` package:
  - `aliases.py` — YAML loader + bijection lint
  - `schemas.py` — pydantic v2 input row schemas (Actor, Report, Incident)
  - `normalize.py` — URL canonicalization + `sha256_title` + tag regex classifier (5 types: actor/malware/cve/operation/sector) + alias-dictionary apply
  - `loader.py` — openpyxl + pandas sheet loader
  - `upsert.py` — repository-pattern upserts for `groups`, `codenames`, `sources`, `reports`, `tags`, `report_tags`, `incidents`, incident-mapping tables
- `services/worker/tests/unit/` — unit tests covering T2–T6 (alias bijection, schema accept/reject, URL edge cases, tag classifier, upsert idempotency against sqlite-memory)
- `services/worker/pyproject.toml` — add `openpyxl`, `pandas`, `pydantic>=2`, `pyyaml`, `sqlalchemy`, `psycopg[binary]`, dev deps: `pytest`, `pytest-cov`, `pytest-asyncio`

### In scope — PR #6 (T7–T9)
- `services/worker/src/worker/bootstrap/cli.py` — `python -m worker.bootstrap` entrypoint, flags: `--workbook`, `--dry-run`, `--limit`, `--errors-path`
- `services/worker/src/worker/bootstrap/errors.py` — JSONL dead-letter writer, exit-code policy (D5 three-branch rule)
- `services/worker/src/worker/__main__.py` (or equivalent wiring) so the CLI is invocable via `python -m worker.bootstrap`
- `services/worker/README.md` — documents the CLI flags, dead-letter schema, and exit-code policy
- `services/worker/tests/integration/test_bootstrap_cli.py` — drives the CLI end-to-end against the fixture, asserts all three exit-code branches
- `.github/workflows/ci.yml` — new `worker-tests` job (pytest + coverage gate ≥70%) and a bootstrap fixture dry-run step

### Out of scope (both PRs, explicit)
- Great Expectations suite → PR #7
- Audit-log row-level insert for bootstrap → PR #7
- Prefect flow registration → PR #8
- RSS/TAXII worker → PR #8
- Frontend changes → Phase 2+
- Incident-to-CVE auto-linking heuristics → Phase 3
- LLM enrichment of tags → Phase 4

---

## 5. Task Breakdown

Dependency order. T1 landed in PR #4 (preflight). T2–T6 land in PR #5. T7–T9 land in PR #6.

| # | PR | Task | Depends on | Est. | Exit criteria |
|:---:|:---:|:---|:---|:---:|:---|
| ~~T1~~ | #4 | BigInt PK migration | — | ~~0.5d~~ | **Done 2026-04-15** (see 0004_bigint_pk_migration.py) |
| **T2** | #5 | `aliases.yml` + YAML loader + bijection lint | T1 | 0.5d | Loader returns `dict[canonical, set[alias]]`; bijection violation fails fast in a unit test |
| **T3** | #5 | Pydantic row schemas (Actor / Report / Incident) | T1 | 0.5d | Schemas reject the 5 failure rows in the fixture; accept the happy rows |
| **T4** | #5 | URL canonicalize + `sha256_title` util | T1 | 0.25d | Unit tests for tracking-param strip, casing, trailing slash, IDN, hash determinism |
| **T5** | #5 | Tag regex 5-type classifier + alias apply | T2, T4 | 0.5d | Covers every tag pattern in design doc §2.3; falls back to `unknown_type` safely |
| **T6** | #5 | Upsert repositories + loader wiring | T3, T5 | 1d | `url_canonical` unique constraint drives idempotency; re-running the fixture load produces zero duplicates; worker coverage ≥70% for this PR's surface |
| **T7** | #6 | CLI entrypoint + dead-letter + exit-code policy | T6 merged | 0.5d | `--workbook`, `--dry-run`, `--limit`, `--errors-path`; the 3 exit-code branches from D5 are covered by tests |
| **T8** | #6 | Integration tests driving the CLI against the fixture | T7 | 0.5d | CLI dry-run returns 0; non-dry first-run populates DB; second non-dry run produces zero new rows; forced-failure fixture asserts >5% → non-zero exit |
| **T9** | #6 | CI extension: `worker-tests` job + bootstrap dry-run step | T8 | 0.25d | `worker-tests` job green on PR; fixture dry-run exits 0 with `fail_rate=0` |

**Estimates:** ~2.75 dev-days for PR #5, ~1.25 dev-days for PR #6.

---

## 6. Risks & Mitigations

| Risk | Severity | Mitigation |
|:---|:---:|:---|
| Real workbook column names differ from v1.0 assumption | High | Build against fixture first; real workbook is exercised only via local `BOOTSTRAP_WORKBOOK_PATH`; column mapping is a config constant, not hardcoded in parsers. |
| URL canonicalization loses signal (two semantically different URLs collapse to same canonical) | High | Canonicalization keeps path + significant query params; strip rules are whitelisted (`utm_*`, `fbclid`, `gclid`) rather than blacklisted. Unit tests include adversarial cases. |
| Alias dictionary entry conflicts (same alias maps to two canonicals) | Med | Loader validates bijection at load time and fails fast with a dictionary-lint error; this is checked by a unit test. |
| `tags` regex classifier over-matches (e.g. `#operation` captures `#op`) | Med | Regex ordered by specificity; `unknown_type` fallback keeps the raw tag for later LLM cleanup rather than silently dropping. |
| >5% fail rate triggers on happy fixture | Med | Fixture YAML tags each row as `happy` or `failure_case`; a stress-test sub-fixture controls when the threshold is expected to trip. |
| PR #5 lands on main in an intermediate state that cannot be executed by an operator | Low | Acceptable: the Bootstrap ETL is internal infrastructure, not a live feature. PR #5 exposes only library APIs tested against the fixture; PR #6 adds the operator-facing CLI. Documented explicitly in each PR description. |

---

## 7. Rollback Plan

- **PR #4 (BigInt)**: Already merged. Rollback would require an empty DB and `alembic downgrade -1`.
- **PR #5 (normalization + upsert)**: Pure additive (new package under `services/worker`, new fixture, new YAML dictionaries, new dev deps). Revert = `git revert`. No CLI exists yet, so nothing can be driven against a real DB from this PR alone.
- **PR #6 (CLI + CI)**: Pure additive on top of PR #5. Revert = `git revert`. Running `worker.bootstrap` against prod DB is manual and gated by operator, so revert leaves the DB untouched.

---

## 8. Acceptance Criteria

### PR #5 is mergeable only when all of the following hold

1. All PR #5 library modules are implemented and unit tested against the fixture.
2. `services/worker/tests/fixtures/bootstrap_sample.xlsx` is regenerable from `bootstrap_sample.yaml` via `scripts/generate_bootstrap_fixture.py`.
3. Upsert repository proves idempotency against sqlite-memory: running the load twice produces identical row counts.
4. Worker pytest coverage ≥70% for the modules introduced by this PR.
5. All existing CI jobs from PR #3/#4 still green.
6. Final external review reports no unresolved critical/high findings.

### PR #6 is mergeable only when all of the following hold

1. PR #5 is merged to main.
2. `python -m worker.bootstrap --workbook services/worker/tests/fixtures/bootstrap_sample.xlsx --dry-run` exits 0 against a clean schema.
3. Re-running the same command non-dry against a fresh DB produces the expected row counts in every target table, and a second run produces zero new rows (idempotency proven end-to-end).
4. `artifacts/bootstrap_errors.jsonl` is created only when there are failures; its schema is documented in `services/worker/README.md`.
5. The three D5 exit-code branches are each exercised by a test.
6. CI `worker-tests` job green.
7. All existing CI jobs from PR #3/#4/#5 still green.
8. Final external review reports no unresolved critical/high findings.

---

## 9. Open Questions

- **Workbook delivery path**: the real v1.0 workbook is not yet staged on this dev box. Blocker for local end-to-end verification against real data before merge. Mitigation: PR #5/#6 CI uses the fixture; real-data smoke happens locally post-merge, with a follow-up issue if column drift is detected.
- **Sectors / countries reference tables**: the 0001 migration defines `incidents` but the mapping tables (`incident_sectors`, `incident_countries`, `incident_motivations`) need to be re-read to confirm naming and FK direction before T6 implementation. Not a decision — a read-before-code checkpoint.

---

## 10. Change Log

- **2026-04-14** — Plan locked. D1–D5 confirmed. Task order T1→T9 set. Acceptance criteria fixed.
- **2026-04-15** — Renumbered to match actual GitHub PR sequence. Preflight is PR #4, Bootstrap ETL is PR #5, Great Expectations + audit is PR #6, Prefect worker is PR #7. File renamed `pr4-bootstrap-etl.md` → `pr5-bootstrap-etl.md`. No scope or decision changes.
- **2026-04-15** — T1 (BigInt PK migration) landed via PR #4; D4 rewritten as historical record.
- **2026-04-15** — PR split applied. PR #5 now covers T2–T6 (normalization + upsert library). New PR #6 covers T7–T9 (CLI + dead-letter + CI). Downstream renumbered: Great Expectations + audit row-level → PR #7; RSS/TAXII worker + Prefect → PR #8. Fixture generator clarified as part of PR #5. D1 tightened to require a YAML source-of-truth + generator script (no hand-edited binary). Scope, decisions, risks, acceptance criteria, and rollback plan all expanded to cover both PRs.

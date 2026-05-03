# P-W1 - LLM Wiki Foundation (Infrastructure + Policy)

**Status:** Draft v0 - 2026-04-26. Design-only phase. No collector, parser, LLM extractor, DB migration, or frontend route ships in this slice.

**Base:** `main` at `b03b3e6` (PR #21 merged). This phase is independent of PR #22/#23/#24/#25 and can be reviewed while the PR stack waits on external signals.

**Why this phase exists:** the dashboard has enough structured CTI data to support a richer analyst surface, but the wiki/LLM pipeline needs a governance layer before any fetcher or extractor writes facts. P-W1 defines the directories, page schema, source policy, staging policy, validation gate, and future dashboard surfaces so P-W2..P-W8 can implement without inventing rules mid-stream.

**Non-goal:** this is not the visual-redesign PR. PR #25 decides the product skin. P-W1 decides the CTI knowledge-base substrate that future routes such as `/sources`, `/codenames`, `/techniques`, and `/wiki` will read.

---

## 0. Lock Summary

These invariants should survive implementation debate:

1. **No LLM output reaches durable DB/wiki truth without a validator gate.** Extractors can write proposals; validators and human review decide promotion.
2. **Raw fetched artifacts are not product content.** Raw HTML/PDF/text belongs in a deduped runtime store; committed wiki pages carry summaries, citations, metadata, and provenance, not wholesale copyrighted source text.
3. **Existing `staging` remains report-ingest/review staging.** Structured wiki/entity claims need a separate future staging surface because their lifecycle is claim-level, not report-level.
4. **Every wiki fact must point back to evidence.** A page without source-backed evidence is a draft note, not canonical knowledge.
5. **P-W1 is policy-first.** It creates a design contract and schema spec; fetch/parse/extract/integrate code starts in P-W2+ only after user review.

---

## 1. Current Repo Evidence

Relevant existing surfaces as of `main@b03b3e6`:

- `sources` table already exists with `name`, `type`, `country`, `website`, and `reliability_default`.
- `codenames` table already exists with `group_id`, `named_by_source_id`, date bounds, `confidence`, and `stix_id`.
- `techniques` and `report_techniques` already exist; the UI uses the aggregate attack matrix but has no `/techniques` route.
- `report_codenames.confidence` and `report_techniques.confidence` already provide confidence-bearing join surfaces.
- `staging` currently models report ingestion: URL/title/raw text/summary/tags/confidence/status/review metadata/promoted report pointer.
- `worker.ingest.staging_writer` writes RSS/TAXII normalized drafts to `staging` using `url_canonical` dedupe.
- No `wiki/` directory exists on `main` yet.

Implication: P-W1 should extend the architecture around existing normalized tables, not replace them.

---

## 2. Goals

1. Define a committed wiki directory shape and page schema that can represent sources, actors, codenames, techniques, conflicts, freshness, and provenance.
2. Define a raw artifact storage policy that is deduped, idempotent, and safe for copyright/ToS constraints.
3. Define the LLM extraction lifecycle: collector -> parser -> extractor -> validator -> human review -> integrator -> auditor.
4. Define future dashboard menu additions and the API surfaces they will need, without implementing those routes in P-W1.
5. Define measurable gates for P-W2..P-W8: source coverage, parse success, extraction precision, auditor health, and UI readiness.

---

## 3. Explicit Non-Goals

- No new API endpoint.
- No DB migration.
- No worker/fetcher/parser implementation.
- No LLM provider invocation or pricing lock.
- No frontend route or navigation change.
- No raw-data backfill.
- No automated edits to `wiki/entities/**` beyond schema/template examples if the user asks for them in a later slice.
- No attempt to publish the dataset or paper artifacts.

---

## 4. Proposed Directory Contract

Runtime/generated stores:

```text
raw_data/
  _index.jsonl              # sha256, source_url, fetched_at, content_type, fetcher, status
  _missing.json             # URL/source failures, categorized and counted
  objects/
    sha256/<first2>/<hash>  # raw bytes, not committed by default
  parsed/
    <hash>.md               # parser output, generated, not canonical truth
```

Committed wiki store:

```text
wiki/
  _meta/
    schema.md               # page schema, naming, linking, confidence, evidence rules
    log.md                  # human-readable pipeline/auditor history
    _missing.json           # derived summary copy from raw_data for UI/audit
    _conflicts.md           # curated conflict register
    _orphans.md             # generated orphan-page/link report
  entities/
    actors/<slug>.md
    codenames/<slug>.md
    malware/<slug>.md       # optional future surface
    techniques/<mitre-id>.md
    vulnerabilities/<cve>.md # optional future surface
  sources/<source-slug>.md
  concepts/
    attribution-consensus.md
    timeline-operations.md
    methodology.md
```

Commit policy:

- Commit `wiki/**` once pages are validated or explicitly marked draft.
- Do not commit `raw_data/objects/**` by default.
- Small parser fixtures may live under `tests/fixtures/raw_data/**`, never under production `raw_data/`.
- Add `.gitignore` entries for raw byte stores in P-W2 if the directory is introduced then.
- `raw_data/_missing.json` is the canonical failure ledger. `wiki/_meta/_missing.json` is a derived, human/UI-facing summary emitted by the auditor/publisher and must be regenerable from the raw ledger plus source metadata.

---

## 5. Wiki Page Schema

All pages use YAML front matter plus Markdown body.

Required common fields:

```yaml
---
slug: lazarus-group
kind: actor | source | codename | malware | technique | vulnerability | concept
canonical_name: Lazarus Group
aliases: []
status: draft | validated | stale | deprecated
confidence: 0.0
last_reviewed_at: 2026-04-26
last_source_seen_at: null
source_count: 0
conflict_count: 0
generated_by: manual | collector | extractor | integrator
evidence:
  - source: mandiant
    report_id: 123
    url: https://example.invalid/report
    captured_sha256: null
    quote_policy: paraphrase
    claim_ids: []
---
```

Body sections by kind:

- `Summary`
- `Evidence`
- `Known Aliases` for actors/codenames/malware
- `Attribution Notes`
- `Conflicts`
- `Timeline`
- `Related Entities`
- `Maintenance Notes`

Evidence rules:

- Prefer paraphrase plus citation over copied source text.
- Short quotes are allowed only when they are necessary to identify a claim and comply with local copyright policy.
- Every claim added by an LLM must include `source_url`, `source_slug`, `captured_sha256`, and `extractor_version` metadata before validation.

---

## 6. Source And Fetch Policy

Collector/fetcher rules for P-W2+:

1. Respect `robots.txt` and site-specific ToS. Public availability is not equivalent to permission to crawl at scale.
2. Use an explicit user agent that identifies the project and contact channel.
3. Deduplicate by `sha256(raw_bytes)` and idempotency key `(url_canonical, fetched_at_floor, content_hash)`.
4. Prefer official/vendor/public report pages over mirrors; use archived copies only when the original is unavailable and the archive allows access.
5. Classify failures into `_missing.json` categories: `not_found`, `robots_disallowed`, `paywall`, `js_required`, `download_error`, `parse_error`, `unsupported_media`, `duplicate`, `other`.
6. Track fetch latency, content type, byte size, and parser selected.
7. Never store credentials, cookies, or analyst session state in raw artifacts.

### 6.1 Korean-Language Source Policy

Korean public CTI sources are first-class inputs, not fallback material. KISA, AhnLab ASEC, ESTsecurity, KrCERT advisories, Korean-language vendor blogs, and Korean government pages should preserve enough language metadata that analysts can audit both the original text and any English synthesis.

Rules for P-W2+:

1. Store parser output in the source language. Do not machine-translate raw parser artifacts in place.
2. Add `lang` and `detected_lang` metadata to raw/parsed indexes; expected values include `ko`, `en`, and `mixed`.
3. LLM extractors may produce normalized English fields for cross-source comparison, but every translated/summarized claim must retain a pointer to the Korean evidence span.
4. Korean proper nouns, campaign names, company names, and malware names must be preserved verbatim when they are evidence-bearing identifiers. Romanization is an alias, not a replacement.
5. Validator prompts/tests must include Korean fixtures before any Korean-source extraction is auto-promoted.
6. UI/wiki pages may show English summaries first, but source pages should record original title, translated title if generated, language, and translator/extractor metadata.

---

## 7. LLM Extraction Lifecycle

Pipeline roles are responsibilities, not a requirement to run eight autonomous agents at once:

| Role | Responsibility | Durable output |
|---|---|---|
| collector | fetch source artifacts and update raw index | `raw_data/_index.jsonl`, `_missing.json` |
| parser | convert HTML/PDF/text into normalized Markdown/text | `raw_data/parsed/<hash>.md` |
| extractor | propose structured claims with evidence spans | future `wiki_claim_staging` rows or JSONL |
| validator | schema validation, confidence checks, contradiction checks | validation report |
| human reviewer | approve/reject/edit claims below trust threshold | decision metadata |
| integrator | update DB and wiki pages idempotently | DB rows + `wiki/**` pages |
| auditor | find drift, stale pages, conflicts, orphan links | `wiki/_meta/*` |
| publisher/exporter | build UI/API/export datasets | future dashboard/API outputs |

Minimum extraction object shape:

```json
{
  "claim_id": "sha256:...",
  "entity_kind": "codename",
  "entity_key": "applejeus",
  "predicate": "associated_with_actor",
  "object_key": "lazarus-group",
  "confidence": 0.86,
  "evidence": {
    "source_url": "https://example.invalid/report",
    "captured_sha256": "...",
    "span_start": 1200,
    "span_end": 1440,
    "paraphrase": "..."
  },
  "extractor": {
    "model": "tbd",
    "prompt_version": "tbd",
    "run_id": "..."
  }
}
```

Validation policy:

- `confidence < 0.80`: auto-reject or require human review; never auto-integrate.
- `0.80 <= confidence < 0.95`: validator must pass and human review is required for attribution-sensitive claims.
- `confidence >= 0.95`: may be auto-promoted only for low-risk metadata after two-source agreement or an existing canonical match.
- Any actor attribution, alias merge, or conflict resolution remains human-review-required until the project has measured extractor precision.

Threshold rationale:

| Threshold | Meaning | Why this value |
|---|---|---|
| `< 0.80` | Low enough that the extractor itself is signaling uncertainty. | Treat as reject/review to avoid turning weak LLM guesses into analyst workload or durable facts. |
| `0.80..0.949` | Plausible claim, still not trusted for attribution-sensitive writes. | This band gives validators and reviewers a queue while the project measures real precision on DPRK CTI sources. |
| `>= 0.95` | High-confidence metadata candidate, not automatic truth. | Even high confidence requires low-risk predicate class plus two-source agreement or an existing canonical match. |

These are policy thresholds, not model calibration claims. P-W4 must measure precision/recall on a reviewed fixture set and can tighten or loosen the numbers only with a plan amendment.

---

## 8. Staging Decision

**Recommendation: do not overload the existing `staging` table for wiki/entity claims.**

Existing `staging` has report-ingest semantics:

- one row per URL/report candidate;
- `url_canonical` uniqueness;
- report promotion into `reports`;
- review statuses tied to report lifecycle;
- `tags_jsonb`, `summary`, and `confidence` as report-level fields.

Wiki/entity extraction needs claim-level semantics:

- many claims per source artifact;
- claims can target different tables/pages from the same report;
- a single report can produce accepted, rejected, and conflicting claims simultaneously;
- alias merges and attribution statements require reviewer notes separate from report acceptance.

Future P-W4/P-W5 should introduce a dedicated table, tentatively `wiki_claim_staging`:

```text
wiki_claim_staging(
  id,
  run_id,
  source_report_id nullable,
  source_url,
  captured_sha256,
  entity_kind,
  entity_key,
  predicate,
  object_kind nullable,
  object_key nullable,
  value_jsonb,
  evidence_jsonb,
  confidence numeric(4,3),
  status pending|approved|rejected|promoted|conflict|error,
  reviewed_by,
  reviewed_at,
  decision_reason,
  promoted_entity_ref nullable,
  created_at
)
```

Reuse the existing review concepts and status names where they fit; do not reuse the report `staging` table itself.

---

## 9. Future Dashboard Surfaces

P-W7 candidate routes:

| Menu | Route | Backing surface | Notes |
|---|---|---|---|
| Sources | `/sources`, `/sources/:id` | `sources` + `wiki/sources/*.md` | reliability, coverage, missing-rate, freshness cards |
| Codenames | `/codenames`, `/codenames/:id` | `codenames`, `report_codenames`, `wiki/entities/codenames/*.md` | alias graph and actor/malware relation graph |
| Techniques | `/techniques`, `/techniques/:id` | `techniques`, `report_techniques`, `wiki/entities/techniques/*.md` | ATT&CK provenance and source-weighted heatmap |
| Wiki Browser | `/wiki/*` | committed `wiki/**` or static export | read-only page viewer and graph view |
| Malware | `/malware`, `/malware/:id` | future table/wiki pages | optional; do not expose until API exists |
| Vulnerabilities | `/vulnerabilities`, `/vulnerabilities/:id` | future table/wiki pages | optional; do not expose until API exists |

Visualization backlog:

1. Source coverage heatmap from `_missing.json` and `_index.jsonl`.
2. Conflict graph from `_conflicts.md` or future claim table.
3. Codename alias network: actor -> alias -> malware/report.
4. Wiki graph view from Markdown links.
5. Confidence distribution and trend from claim/report join tables.
6. Wiki freshness map by `last_reviewed_at` and `last_source_seen_at`.
7. Incident-to-report fanout comparison.
8. ATT&CK heatmap with provenance weighting.

---

## 10. Paper/Research Tracks

P-W8 can export datasets and generated analysis pages for research, but paper work should not block product phases.

Candidate tracks:

1. Source consensus in DPRK attribution claims.
2. Codename normalization as a graph problem.
3. Operational cost/quality study for LLM-assisted CTI wiki maintenance.
4. Longitudinal DPRK targeting shift, 2009-2026.
5. FTS-first hybrid search versus LLM/wiki retrieval.
6. Public-source DPRK cyber operation timeline.

P-W1 policy requirement: every research export must include reproducibility metadata: source set version, extraction prompt version, validation threshold, rejected-claim counts, and known coverage gaps.

---

## 11. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| LLM hallucinated attribution enters DB/wiki | severe trust loss | validator gate, confidence threshold, human review for attribution/alias changes |
| Cost runaway on 3458+ reports | operating cost | sha256 idempotency, cache, per-run budget, model tiering, stop-on-budget |
| Copyright/ToS violation | legal/project risk | robots/ToS respect, no raw wholesale text in committed wiki, explicit user agent |
| Wiki and DB drift | data reliability | integrator writes both or writes an outbox; auditor reports drift daily |
| raw_data disk growth | infra cost | sha256 dedupe, compression, retention policy, future object store |
| JS/paywall pages lower coverage | incomplete corpus | categorize in `_missing.json`; optional Playwright fetcher only after policy review |
| Markdown sprawl | maintainability | `wiki/_meta/schema.md`, templates, auditor checks, link rules |
| Overloaded staging lifecycle | reviewer confusion | separate claim staging table; preserve report staging semantics |

---

## 12. Open Items For User Review

| ID | Question | Recommended answer |
|---|---|---|
| OI1 | Reuse existing `staging` for wiki/entity claims? | **B - no.** Keep existing `staging` for report ingest; add `wiki_claim_staging` in P-W4/P-W5. |
| OI2 | Where should raw fetched bytes live initially? | **A - local ignored `raw_data/objects/**`** with sha256 index; revisit S3/MinIO after volume is measured. |
| OI3 | Should validated wiki pages be committed to git? | **A - yes** for curated pages and `_meta` reports; raw bytes stay ignored. |
| OI4 | Initial source acquisition target for P-W2? | **B - 60%** raw artifact coverage across reports, with `_missing.json` explaining the rest. |
| OI5 | Initial extractor auto-promotion threshold? | **C - none for attribution claims.** Human review required until measured precision >= 90%. |
| OI6 | LLM budget lock? | **Defer exact dollar estimate to P-W4 pre-kickoff** using current provider pricing; P-W1 only locks budget enforcement and idempotency. |
| OI7 | Start P-W7 UI before P-W5 has integrated pages? | **B - no.** Build UI spec early, but implementation waits for first 100 validated pages. |
| OI8 | Which `_missing.json` is canonical? | **A - `raw_data/_missing.json`.** `wiki/_meta/_missing.json` is a derived summary for people/UI and must be regenerable. |

---

## 13. Phase Roadmap

| Phase | Scope | Deliverable | Gate |
|---|---|---|---|
| P-W1 | infra + policy design | this plan + future `wiki/_meta/schema.md` draft | user review |
| P-W2 | collector/fetcher | sha256 raw store, `_index.jsonl`, `_missing.json` | coverage >= 60% or categorized failures |
| P-W3 | parser | HTML/PDF/text -> parsed Markdown/text | random 30-doc human spot check |
| P-W4 | extractor + validator | claim schema, LLM extraction, validator, pending queue | human-reviewed precision >= 90% |
| P-W5 | integrator | idempotent DB/wiki updates, first 100 entity pages | auditor passes |
| P-W6 | auditor | conflicts, missing, stale, orphan reports | daily report generated |
| P-W7 | dashboard routes | `/sources`, `/codenames`, `/techniques`, `/wiki` | visual + route tests |
| P-W8 | research/export | analysis pages and dataset export | separate research review |

---

## 14. P-W1 Deliverables

This design PR should include only:

1. `docs/plans/pw1-llm-wiki-foundation.md`.
2. Optionally, after user review, `wiki/_meta/schema.md` as a template contract.
3. Optionally, `.gitignore` entries for `raw_data/objects/**` if P-W1 creates the directory. The current draft does not create it.

No CI job is required for P-W1 unless markdown lint is later introduced.

### 14.1 Acceptance Checklist

P-W1 is ready for sign-off when:

- [ ] The user agrees that `raw_data/_missing.json` is the canonical fetch/parse failure ledger.
- [ ] The user agrees that existing `staging` remains report-ingest staging and future wiki/entity claims use a separate claim-staging surface.
- [ ] The user agrees that Korean-language sources are first-class and parser output preserves original language.
- [ ] The user accepts the initial confidence threshold policy as a starting gate, with P-W4 measurement required before auto-promotion.
- [ ] The user accepts the P-W2 coverage target of 60% raw artifact acquisition with categorized gaps.
- [ ] The user accepts that P-W1 ships no code, no DB migration, no API route, and no UI route.

---

## 15. Implementation Notes For Later Phases

- P-W2 should reuse existing worker patterns for idempotent writes and audit logging.
- P-W4 should reuse the llm-proxy boundary for model calls if the selected provider is compatible; otherwise add a provider adapter behind that boundary rather than leaking keys into workers.
- P-W5 should avoid direct DB+wiki dual-write without recovery. If one side can fail after the other succeeds, use an outbox/retry record and let the auditor expose pending drift.
- P-W7 should not iframe arbitrary local Markdown. Prefer static Markdown-to-HTML rendering with sanitized output and route-level data loading.
- Every phase should add one small, reviewable gate rather than a large end-to-end batch that is hard to debug.

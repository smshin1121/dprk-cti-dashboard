# P-W2 - Collector + Fetcher (Raw Artifact Acquisition)

**Status:** Draft v1 - 2026-04-26. Implementation phase. Builds the first executable layer of the LLM Wiki pipeline. Parser/extractor/integrator/auditor remain in P-W3..P-W6.

**Base:** `main` at `b03b3e6` (PR #21 merged). Independent of #22/#23/#24/#26-visual. Depends on P-W1 (PR #25) being signed off - the policy contract this phase implements.

**Why this phase exists:** P-W1 locked the wiki/raw-data policy but ships no code. P-W2 is the first phase where bytes start flowing - known report URLs (`reports.url_canonical`) become deduped, hashed, traceable artifacts on local disk, and every failure is categorized rather than silent. Without this layer, every later phase (parser, extractor, validator, integrator) would have to re-derive provenance or accept undeclared coverage gaps.

**Non-goal:** P-W2 does not parse, summarize, extract, or store anything in the database. P-W2 produces raw bytes plus a structured fetch log on local disk, nothing else.

---

## 0. Lock Summary

Invariants this phase commits to:

1. **Fetcher input is the existing `reports.url_canonical` set.** P-W2 does not discover new URLs via web search, RSS expansion, or sitemap crawl. Those expansions are P-W3+ topics.
2. **Raw bytes are immutable.** Once stored under `raw_data/objects/sha256/<aa>/<sha>` they are never modified. Re-fetch producing different bytes creates a new object; both records remain in the ledger.
3. **Every URL attempt is recorded.** Success or failure, the attempt becomes a row in `raw_data/_index.jsonl`. There is no silent skip, no swallowed exception.
4. **Every failure is categorized.** The category enum is closed (see Section 8). `other` is permitted but should trigger a follow-up issue, not an accumulated dump.
5. **`raw_data/_missing.json` is canonical** (per P-W1 Section 4). `wiki/_meta/_missing.json` is not produced in P-W2.
6. **Pattern reuse, not direct reuse, of `worker.ingest.fetcher`.** The existing `RssFetcher` is feed-shaped, hardcodes a User-Agent, and returns no content-type/elapsed/redirect metadata - see Section 1 evidence and Section 4 plan. P-W2 either extracts a generic raw fetcher or writes a new one in the same shape.
7. **No LLM call in P-W2.** The fetcher is deterministic.
8. **No new DB table in P-W2.** All durable output is on disk. DB mirroring is a P-W6 auditor option, not a P-W2 deliverable.

---

## 1. Current Repo Evidence

What already exists on `main@b03b3e6` that P-W2 builds on or adapts around:

- `services/worker/src/worker/ingest/fetcher.py:60` - `RssFetcher` class wrapping `httpx.AsyncClient`. **Feed-shaped:** `fetch(feed: FeedConfig, state: FeedStateRow | None = None) -> FetchOutcome`. **Hardcoded User-Agent** (`_USER_AGENT` constant at module level). **`FetchOutcome` returns only** `status_code, content, etag, last_modified, error` - no `content_type`, no `elapsed_ms`, no redirect chain. **Implication for P-W2:** the `httpx.AsyncClient` setup, conditional-GET pattern (ETag / Last-Modified), and exception-to-outcome mapping are good prior art, but P-W2 needs a generic raw fetcher that takes a URL plus per-call User-Agent and returns the richer metadata required by Section 6 schema. Either extract `_fetch_url` from `RssFetcher` into a shared helper, or write a sibling raw fetcher in `worker/raw_acquisition/fetcher.py` that mirrors the testable shape (constructor takes injectable `httpx.AsyncClient`, `fetch(url, headers, conditional_state)` returns dataclass).
- `services/worker/src/worker/ingest/taxii/fetcher.py` - similar TAXII-flavored fetcher; same caveat.
- `services/worker/src/worker/ingest/staging_writer.py:44` - `INSERT ... ON CONFLICT DO NOTHING` idempotency pattern (postgres + sqlite dialect-aware). Pattern reusable for any future DB mirroring; **not used in P-W2**.
- `services/worker/src/worker/ingest/audit.py` - row-level structured event log shape. Pattern reusable for the per-run summary.
- `reports.url_canonical` (UNIQUE) - ingest target set, ~3458 rows on the dev DB. Coverage gate in Section 11 is over the subset where `url_canonical IS NOT NULL`.
- `data/dictionaries/` - exists for normalization tables. Safe to add a P-W2 fixture/dictionary (e.g., known-paywall hosts, JS-required-host hints) here.
- `.gitignore` - does not currently ignore `raw_data/`. P-W2 will add the relevant entries.

What does NOT exist yet:

- A generic, URL-shaped raw fetcher returning content-type/elapsed/redirect metadata.
- A persistent fetch log on disk (`_index.jsonl`).
- A failure category taxonomy.
- A sha256-addressed object store.
- A coverage measurement script.

---

## 2. Goals

1. Ship a `worker/raw_acquisition/` module that, given the current `reports.url_canonical` set, produces:
   - Deduped raw artifacts in `raw_data/objects/sha256/<first2>/<sha256>`.
   - One JSONL line per fetch attempt in `raw_data/_index.jsonl` (success or failure).
   - A categorized `raw_data/_missing.json` rebuildable from the JSONL ledger.
2. Achieve **>= 60% raw artifact acquisition** across reports where `url_canonical IS NOT NULL`. The remaining <= 40% must be categorized in `_missing.json`, not silently absent.
3. Document one CLI entry point that is idempotent, resumable, and budget-bounded (max attempts, max bytes, max wall time).
4. Keep all of the above behind feature flags / opt-in env vars; default `main` runtime behavior unchanged.

---

## 3. Explicit Non-Goals

- No parser. HTML/PDF/text are stored as bytes; no normalization to Markdown.
- No LLM extraction.
- **No new DB table.** Durable output is on-disk (`_index.jsonl`, `_missing.json`, `raw_data/objects/...`). A worker-side DB mirror of fetch attempts is intentionally Deferred to P-W6 auditor; not in P-W2 scope.
- No frontend route, API endpoint, or UI surface.
- No scheduled job (Prefect/cron) wiring. P-W2 ships the CLI; scheduling is opt-in for P-W6+.
- No URL discovery beyond `reports.url_canonical`. (Wayback Machine fallback is recorded as a candidate field only - see Section 14 risk register.)
- No headless browser / Playwright fetcher. JS-required URLs are categorized and skipped in P-W2; resolution is P-W2.1+ behind a separate flag.
- No paywall bypass.

---

## 4. Module Layout

New code:

```text
services/worker/src/worker/raw_acquisition/
  __init__.py
  __main__.py                # dispatches python -m worker.raw_acquisition -> cli.main()
  cli.py                    # python -m worker.raw_acquisition fetch [...]
  collector.py              # selects URLs from reports.url_canonical, deduplicates, batches
  fetcher.py                # generic raw fetcher (URL-shaped, not feed-shaped); see Section 1
  hashing.py                # sha256 streaming hasher + path layout
  index.py                  # _index.jsonl writer (atomic appends)
  classify.py               # exception/response -> failure category
  missing.py                # build _missing.json from _index.jsonl
  coverage.py               # measure coverage % over reports.url_canonical
  config.py                 # env vars, budgets, user agent string
tests/unit/test_raw_acquisition_*.py
tests/integration/test_raw_acquisition_e2e.py
```

Reuse stance:

- `worker.ingest.fetcher` is **prior art for the httpx setup pattern**, not a drop-in dependency. Either extract the conditional-GET / exception-mapping helpers into a shared utility, or implement `worker/raw_acquisition/fetcher.py` as a sibling that mirrors the same testable shape (injectable client, dataclass outcome). Decision is left to the implementation PR.
- `worker.ingest.audit` patterns inform the per-run summary file format.
- `worker.ingest.staging_writer` ON CONFLICT pattern is **not used** in P-W2 because P-W2 writes no DB rows.

---

## 5. `raw_data/` Layout (Concrete)

```text
raw_data/
  _index.jsonl                    # append-only fetch attempt log; canonical
  _missing.json                   # derived; rebuildable from _index.jsonl
  objects/
    sha256/
      <first2 hex>/
        <full sha256 hex>         # raw bytes; no extension, MIME tracked in index
  runs/
    <run_id>/
      summary.json                # per-run aggregates: attempted/succeeded/failed-by-category/bytes/wall_time
      _index.jsonl                # per-run subset of root _index.jsonl (symlink or copy depending on OS)
```

`.gitignore` adds `raw_data/objects/`, `raw_data/runs/`, and the JSONL/JSON files. Test fixtures live under `tests/fixtures/raw_data_samples/` and are explicitly committed.

---

## 6. `_index.jsonl` Line Schema

One JSON object per line. Newline-delimited. Append-only. UTF-8.

```json
{
  "ts": "2026-05-01T12:34:56.789Z",
  "run_id": "01HXY...",
  "report_id": 1234,
  "url": "https://example.invalid/report.pdf",
  "url_canonical": "https://example.invalid/report.pdf",
  "fetcher": "httpx",
  "user_agent": "dprk-cti-collector/0.1 (+contact@example)",
  "outcome": "ok | failed",
  "http_status": 200,
  "content_type": "application/pdf",
  "content_length": 482113,
  "sha256": "a1b2...",
  "object_path": "raw_data/objects/sha256/a1/a1b2...",
  "dedupe_of_sha256": null,
  "elapsed_ms": 1820,
  "redirected_from": [],
  "category": null,
  "category_detail": null,
  "etag": "\"abc\"",
  "last_modified": "Tue, 01 May 2026 ..."
}
```

Field semantics:

- Failure rows leave `sha256/object_path/content_*` null, set `outcome=failed`, and fill `category` + `category_detail`. A robots-denied URL is represented as `outcome=failed`, `category=robots_disallowed`; there is no separate skipped outcome.
- Successful rows that hit an existing object via sha256 dedupe set `outcome=ok`, `category=duplicate` (advisory), and **`dedupe_of_sha256`** to the canonical sha. The `object_path` points at the existing object; no new bytes are written.
- `category=duplicate` is a successful, advisory marker on the ledger. It is **not** counted in `_missing.json` (see Section 7).

---

## 7. `_missing.json` Schema

```json
{
  "run_id": "01HXY...",
  "url_set_sha256": "f00d...",
  "generated_at": "2026-05-01T12:40:00Z",
  "totals": {
    "reports_with_url": 3401,
    "fetched_ok_unique_objects": 2120,
    "fetched_ok_dedupe_advisories": 47,
    "missing": 1234,
    "coverage_pct": 63.7
  },
  "by_category": {
    "not_found": 410,
    "robots_disallowed": 88,
    "paywall": 192,
    "js_required": 240,
    "download_error": 121,
    "parse_error": 0,
    "unsupported_media": 17,
    "other": 166
  },
  "items": [
    {
      "report_id": 1234,
      "url_canonical": "...",
      "category": "paywall",
      "category_detail": "HTTP 401 with WWW-Authenticate header",
      "first_attempted": "2026-04-30T...",
      "last_attempted": "2026-05-01T...",
      "attempts": 2,
      "wayback_candidate": "https://web.archive.org/web/2024*/..."
    }
  ]
}
```

Notes:

- `parse_error` count is 0 in P-W2 (no parser). Field is reserved for P-W3 and surfaces here for forward compatibility.
- `duplicate` is **not** an `_missing.json` category. It is a successful-row advisory on the ledger only. Coverage counts dedupe advisories among `fetched_ok_*` totals (one report covered by an existing sha is still covered).
- `url_set_sha256` pins the input URL set the run was scoped against; see Section 11.

---

## 8. Failure Category Enum (Closed Set, Missing Only)

The 8 categories below are the **failure** categories that flow into `_missing.json.by_category`. `duplicate` is NOT in this set; it is an advisory on successful ledger rows (Section 6).

| Category | Trigger | P-W2 default action |
|---|---|---|
| `not_found` | HTTP 404, 410, DNS NXDOMAIN | record, skip |
| `robots_disallowed` | URL disallowed by `robots.txt` for our user agent | record, skip; never retry |
| `paywall` | HTTP 401/402/403 with auth/paywall heuristics | record, skip |
| `js_required` | Empty/near-empty body or known SPA shell heuristics | record, skip; flag for P-W2.1 Playwright option |
| `download_error` | Timeout, connection reset, TLS error, partial read, 5xx after retries | record, retry up to budget |
| `parse_error` | (reserved for P-W3) | n/a in P-W2 |
| `unsupported_media` | Content-Type not in `{text/html, application/pdf, text/plain, application/xhtml+xml}` allowlist | record, skip |
| `other` | Anything else | record with full exception detail; **must trigger a follow-up issue** if count > N per run |

Any expansion of this enum requires a plan amendment, not a code-only change.

---

## 9. Idempotency + Resume Rules

- Run is keyed by `run_id` (ULID/UUID). Multiple concurrent runs are not supported in P-W2.
- Resume: a new run reads the existing `_index.jsonl`, skips reports whose latest attempt was `ok` and whose `object_path` (or `dedupe_of_sha256` target) still exists, and re-attempts everything else under per-run budget caps.
- Per-URL attempt cap: 3 across all runs (configurable). After cap, category is locked unless explicitly reset via CLI flag.
- Per-run budget: max wall-time, max URLs attempted, max total bytes. Defaults conservative; tuned in pilot run.
- Robots.txt cache TTL: 24 hours per host.
- ETag / Last-Modified: stored in `_index.jsonl`. Conditional GET on next attempt avoids re-downloading unchanged objects.
- **sha256 dedupe:** if a new fetch produces a sha already on disk for a different `report_id` or `url`, write a successful-but-advisory ledger row (`outcome=ok`, `category=duplicate`, `dedupe_of_sha256=<existing>`) and do not re-store bytes. This is success, not failure, and does not appear in `_missing.json`.

---

## 10. CLI Interface

```bash
# Dry run: list how many URLs would be attempted, no network calls.
python -m worker.raw_acquisition plan --limit 50

# Actual fetch with a small budget.
python -m worker.raw_acquisition fetch \
  --max-urls 100 \
  --max-wall-time 600 \
  --max-bytes-per-url 10485760 \
  --user-agent "dprk-cti-collector/0.1 (+contact@example)"

# Rebuild _missing.json from _index.jsonl (no network).
python -m worker.raw_acquisition missing --rebuild

# Coverage report only (no network).
python -m worker.raw_acquisition coverage
```

All commands are idempotent. `fetch` resumes from last `_index.jsonl` state.

---

## 11. Coverage Measurement Methodology

Coverage is **ledger-state coverage** keyed by the input URL set:

```
url_set_sha256 = sha256(sorted_join("\n", reports.url_canonical WHERE url_canonical IS NOT NULL))
coverage_pct   = fetched_ok_count / reports_with_url_count * 100
```

Where:

- `reports_with_url_count` = `SELECT COUNT(*) FROM reports WHERE url_canonical IS NOT NULL`.
- `fetched_ok_count` = number of distinct `report_id` whose **latest** `_index.jsonl` row at run-end has `outcome=ok` AND whose `object_path` (or `dedupe_of_sha256` target) exists on disk.

The coverage figure is the ledger state at run-end, not just the rows written by the current run. A resume run that adds the final 5% to push from 55% to 60% is exactly the intended workflow.

The 60% gate is satisfied when:

1. `url_set_sha256` is recorded in the run summary, AND
2. `coverage_pct >= 60.0` for that `url_set_sha256` ledger state, AND
3. The 100% remainder is fully classified across `_missing.json.by_category` (sum of categories + `fetched_ok_*` totals = `reports_with_url`).

Reproducibility requires the run summary to record:

1. `url_set_sha256`.
2. `run_id`.
3. The configuration (user agent, budgets, retry caps).
4. The DB snapshot identifier (e.g., a content hash of `(reports.id, reports.url_canonical)` ordered).

Coverage reports are emitted to `raw_data/runs/<run_id>/summary.json`.

---

## 12. Test Plan

Unit:

- `hashing.py`: streaming sha256 over chunked input matches one-shot hash; path layout deterministic.
- `classify.py`: each enum category triggered by exact response/exception fixtures (use `respx`/`pytest-httpx` for HTTP fixtures).
- `index.py`: append is atomic; concurrent appenders simulated via threads must produce well-formed JSONL.
- `missing.py`: rebuild from a synthetic `_index.jsonl` matches expected `_missing.json`. Specifically asserts `duplicate` rows do NOT contribute to `by_category` and DO count toward `fetched_ok_dedupe_advisories`.
- `coverage.py`: percentage math over a fixture matches a hand-calculated value; `url_set_sha256` is stable across reorderings of the same set.

Integration:

- End-to-end pilot run against a 50-URL fixture set served from a local httpx mock transport. Asserts `_index.jsonl` has 50 lines, object store contains expected sha set, `_missing.json` categories sum to (50 - successful unique - dedupe advisories).
- Resume test: kill mid-run, restart, verify only un-attempted URLs are re-attempted and totals match.
- Robots.txt test: a fixture host with a denying `robots.txt` produces only `robots_disallowed` rows for that host.
- Duplicate test: two URLs serving identical bytes produce two `_index.jsonl` rows but one object on disk; second row has `outcome=ok`, `category=duplicate`, `dedupe_of_sha256` set to the first sha; `_missing.json` does not list either.

CI:

- Add a new pytest mark `raw_acquisition` opt-in in CI; no production network calls in CI.
- No new live-network step.

---

## 13. Open Items For User Review

| ID | Question | Recommended answer |
|---|---|---|
| OI1 | Run a single pilot fetch on the dev DB before merging the implementation PR? | **A - yes.** A 50-URL pilot validates the categorizer and surfaces enum gaps cheaper than fixing them post-merge. |
| OI2 | Wayback Machine fallback in P-W2 default flow? | **B - no.** Track `wayback_candidate` field in `_missing.json` only. Active fallback is P-W2.1 behind a flag. |
| OI3 | Playwright JS-render fetcher in P-W2? | **B - no.** Categorize as `js_required` and defer to P-W2.1. |
| OI4 | Per-host concurrency caps? | **A - yes.** Default 1 concurrent request per host, 8 across hosts. Polite-by-default. |
| OI5 | Commit P-W2 plan as a PR before any code lands? | **A - yes.** Same pattern as P-W1: docs PR first (this plan), implementation PR after sign-off. |
| OI6 | Acceptable to call out specific Korean publishers in fixture set (KISA, AhnLab, ESTsecurity)? | **A - yes.** Their public advisory pages are within the public-source assumption. Robots.txt still respected per host. |
| OI7 | Extract a generic raw fetcher into `worker/_shared/` or live as `worker/raw_acquisition/fetcher.py` sibling? | **B - sibling first.** Keep the change blast-radius small; revisit shared extraction in P-W6 if a third caller emerges. |

---

## 14. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Mass fetch triggers rate-limiting / IP block | coverage stalls + reputation harm | per-host concurrency cap, jittered backoff, explicit user agent, opt-in via flag, conservative defaults |
| robots.txt fetch fails / inconsistent | unsafe fetch decisions | fail-closed: if robots.txt is unreachable, treat as `robots_disallowed` for that host until next TTL expiry |
| `raw_data/objects/` growth pressures local disk | infra | sha256 dedupe is the first line; total bytes budget; per-URL bytes cap; future cold storage |
| ETag/Last-Modified bugs cause re-downloads | wasted bandwidth | conditional GET unit test + integration test |
| sha256 collision (vanishingly improbable, included for completeness) | confused provenance | log + alert; block re-store and surface for manual investigation |
| JSONL append corruption on crash | partial line | open in append+sync mode, write line-by-line, parser tolerates trailing partial line |
| Per-run budget too tight for first pilot | low coverage | start small (50 URLs, 10 min wall), iterate |
| Coverage 60% gate unreachable from current corpus | phase blocked | fallback escalation: surface category histogram + propose enum extension or P-W2.1 unblockers; do not weaken the gate silently |
| `url_set_sha256` shifts mid-run because new reports land | coverage denominator drift | the run records the `url_set_sha256` it scoped; a later corpus change is a new run, not a moving target |

---

## 15. Acceptance Criteria

P-W2 implementation PR is mergeable when all of:

- [ ] Plan PR (this doc) merged to `main`.
- [ ] `services/worker/src/worker/raw_acquisition/` ships with the modules listed in Section 4.
- [ ] All Section 12 unit tests pass.
- [ ] At least one integration test passes on CI (mocked transport).
- [ ] Pilot run on dev DB produces a `_index.jsonl` and `_missing.json` consistent with Section 11 measurement; coverage >= 60%. The `_missing.json.by_category` sum plus `fetched_ok_*` totals must still account for 100% of the URL set. If coverage is below 60%, Section 14 risk escalation is triggered; the gate is not weakened by category completeness alone.
- [ ] `.gitignore` updated for `raw_data/objects/`, `raw_data/runs/`, JSONL/JSON.
- [ ] No DB migration. No API route. No UI route. No new DB table.
- [ ] PR body links to PR #25 (P-W1) and Section 14.1 sign-off as the policy reference.

---

## 16. Implementation Notes For Later Phases

- P-W3 (parser) reads `raw_data/objects/sha256/...` keyed by `_index.jsonl` rows where `outcome=ok` and `content_type` is in supported set. Parser writes to `raw_data/parsed/<sha>.md`. Duplicate-advisory rows do not produce a second parser pass.
- P-W4 (extractor) consumes `raw_data/parsed/<sha>.md` plus the `_index.jsonl` provenance row. Every extracted claim must carry the `sha256` and `report_id` that it derives from. Dedupe-advisory rows expose multiple `report_id` to the same `sha`, so one parsed artifact can be the evidence for many reports.
- P-W6 (auditor) consumes `_index.jsonl` and `_missing.json` to surface staleness, retry exhaustion, and category drift. If JSONL streaming gets painful at this scale, P-W6 may introduce a worker-side mirror table - that is the sanctioned home for the option Deferred from P-W2 Section 3.
- The `js_required` category accumulating > N% of the `_missing.json` total is the trigger to schedule P-W2.1 (Playwright fetcher).

---

## 17. P-W2 Plan Doc Deliverables (this PR)

This design PR should include only:

1. `docs/plans/pw2-collector-fetcher.md` (this document).

No code, no test, no CI change in this PR. The implementation PR is a separate slice that this plan signs off.

### 17.1 Acceptance Checklist (this plan PR)

P-W2 plan PR is ready for sign-off when:

- [ ] The user agrees that the existing `worker.ingest.fetcher` is **pattern reuse, not direct reuse**, and a new generic raw fetcher is part of P-W2 scope.
- [ ] The user agrees that `category=duplicate` is a successful-row advisory and is **not** an `_missing.json` category.
- [ ] The user agrees that **no new DB table** is in P-W2 scope; DB mirroring is Deferred to P-W6.
- [ ] The user agrees that coverage is measured as ledger-state coverage at run-end, keyed by `url_set_sha256`, and the 60% gate applies to that ledger state.
- [ ] The user accepts the closed 8-category failure enum (`duplicate` removed) and the `other`-triggers-issue rule.
- [ ] The user accepts that P-W2 plan PR ships no code, no test, no CI change.

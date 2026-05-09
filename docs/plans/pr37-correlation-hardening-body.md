# Phase 3 Slice 3 PR-C — D-1 Correlation Hardening + UAT

**Scope:** Verification PR. Closes umbrella spec §11 PR-C ("D-1 hardening +
UAT") on top of the merged D-1 stack (PR #28 BE primitives + PR #36 FE
visualization). No production behavior change — adds Playwright E2E
coverage of UAT 1-5, an opt-in NFR-1 perf smoke, a 6th Lighthouse audit
target, and a small cosmetic refactor of the X/Y catalog dropdown.

- **FE additions**: Q1 catalog grouping (`Reports` / `Incidents` section
  headers in the X + Y dropdowns of `CorrelationFilters.tsx`), Playwright
  spec `tests/e2e/correlation-uat.spec.ts` covering UAT 1-5, 6th Lighthouse
  target row in `apps/frontend/lighthouse/README.md`, 2 new i18n keys
  (`correlation.filters.groupReports` + `groupIncidents`) wired through
  `Resources` interface + parity test.
- **BE additions**: `services/api/tests/perf/test_correlation_p95.py` (NFR-1
  smoke), `tests/perf/conftest.py` opt-in gate (`PERF_TEST=1` env var),
  `tests/perf/__init__.py` matching sibling-dir convention, `pytest.ini`
  `perf:` marker registration. **Zero production BE behavior change** —
  the perf test calls the existing `/api/v1/analytics/correlation` endpoint
  unchanged; OpenAPI snapshot diff at PR head is empty.
- **CI**: `.github/workflows/ci.yml` adds a `correlation-perf-smoke` job
  gated on `workflow_dispatch` (manual trigger only — NOT on push / PR)
  per plan §8 Q-C1 default + R-C2 mitigation. The default 12-check
  PR-event surface is preserved unchanged. (PR-C's `chore/*` branch is
  outside the `on.push.branches: ["main", "feat/**"]` filter at
  `.github/workflows/ci.yml:5`, so this branch sees 12 PR-event checks
  on push — not 24 like PR #36's `feat/**`-matching branch saw. See
  AC #14 for full reasoning.)

**Why:** PR #36 shipped the D-1 visualization with its T13 + T14
verification gates carved out (T13 live `pnpm pact:provider` replay +
T14 dev-triad smoke) — Codex pre-merge round adjudicated SAFE TO MERGE
without them given 24/24 CI green + accepted auto-proceed signal, with
the explicit understanding that the umbrella spec's UAT 1-5 + NFR-1 +
Lighthouse 6-target loop ship in this hardening PR. Plan §1 enumerates
the 5 deliverables; this PR closes them.

**Base:** `main` directly (current HEAD `bfa2374` — PR #36 merge
2026-05-09T09:12:41Z). No stack — PR #28 (BE) and PR #36 (FE) are both
already on main. No base-flip risk per `pitfall_stacked_pr_merge_base_flip`.

**Branch:** `chore/p3.s3-correlation-hardening`.

**Plan:** `docs/plans/pr37-correlation-hardening.md` v1.0 + T-1 r1 fold
(renamed from `correlation-hardening.md` at T7 push per
`plan_doc_convention`; PR number #37 confirmed via `gh pr list` after
PR #36's merge).

---

## What lands (17 commits, 15 files / ~1,800 insertions / 26 deletions at the T7 PR-as-diff r2 fold head; verify with `git diff --shortstat main..HEAD`. Reference-point ladder, each entry verifiable via `git diff --shortstat main..<sha>`: cddd3b6 T6 base+r1 = 1,686; ea6bfb0 T6 r2 = 1,692; 09fecb7 T6 r3 = 1,700; 4fe0ccd T7 push base = 1,702; f917165 T7 fix #1 (UAT 2 + UAT 5 part 1) = 1,739; 55c4929 T7 fix #2 (UAT 5 dropdown-close) = 1,764; 30f87e9 T7 r0 sync = 1,774; 7d6f074 T7 PR-as-diff r1 fold = 1,782. Each T6 fold commit edited only the body; T7 push base renamed plan + body to `pr37-*` (+15 / -13); T7 fix #1 + #2 modified only `correlation-uat.spec.ts` — per-commit deltas are +45 / -8 then +31 / -6 (sum +76 / -14 per-commit; the -14 lines were internal to the chain so the cumulative `git diff main..HEAD` deletion count stays at 26 unchanged from T7 push base). File count stays flat at 15 across the entire chain.)

| Commit | Phase | Change |
|:---|:---|:---|
| `b8cf2cf` | T-1 (plan) | docs(plan): correlation-hardening v1.0 — initial draft against main@bfa2374 |
| `eb2ea52` | T-1 r1 fold | docs(plan): correlation-hardening T-1 r1 fold — Codex 3 HIGH + 3 MED + 2 LOW |
| `389db16` | T1 base | docs(lighthouse): correlation-hardening T1 — add /analytics/correlation as 6th audit target |
| `a7ff074` | T1 r1 fold | docs(lighthouse): correlation-hardening T1 r1 fold — Codex 1 LOW (count prose drift) |
| `176c76f` | T2 base + r1 | feat(correlation-hardening): T2 — Q1 catalog grouping by schema root + r1 fold |
| `0e5a62c` | T3 base + r1 + r2 | feat(correlation-hardening): T3 — Playwright UAT 1-5 spec + r1+r2 fold |
| `d5ce424` | T4 base | feat(correlation-hardening): T4 — NFR-1 perf smoke + opt-in marker + workflow_dispatch CI job |
| `cddd3b6` | T6 base + r1 fold | docs(correlation-hardening): T6 — PR body draft + r1 fold (Codex 3 MED + 3 LOW count-narrative drift) |
| `ea6bfb0` | T6 r2 fold | docs(correlation-hardening): T6 r2 fold — Codex 2 LOW (count-narrative + byte-match drift continues) |
| `09fecb7` | T6 r3 fold | docs(correlation-hardening): T6 r3 fold — Codex 2 LOW (CI-surface drift in scope intro + 🟡 pending bullet) |
| `4fe0ccd` | T7 push base | docs(correlation-hardening): T7 — pr37 rename + post-T6 body sync (per `plan_doc_convention` + `pattern_codex_body_review_loop`) |
| `f917165` | T7 fix #1 | fix(correlation-hardening): T7 — UAT 2 query window + UAT 5 UserMenu open (first-CI failures) |
| `55c4929` | T7 fix #2 | fix(correlation-hardening): T7 — UAT 5 dropdown-close after locale-toggle (Radix aria-hidden focus-trap) |
| `30f87e9` | T7 r0 sync | docs(correlation-hardening): T7 r0 — post-CI-green body sync (🟡 → ✅ for UAT 1-5 + AC #11/12/13/14; +2 fix commit rows + stat ladder extended) |
| `7d6f074` | T7 PR-as-diff r1 fold | docs(correlation-hardening): T7 PR-as-diff r1 fold — Codex 2 LOW (f917165 stat ladder + UAT 2 effective_n comment, count-narrative drift continues) |
| _(this commit)_ | T7 PR-as-diff r2 fold | docs(correlation-hardening): T7 PR-as-diff r2 fold — Codex 3 LOW (header stat + AC SHA refs + GitHub PR body sync, drift continues at PR-as-diff layer) |

11 Codex review rounds across **task gates** T-1..T4 (T-1=2 [r1 + r2],
T1=2 [r1 + r2], T2=3 [r1 + r2 + r2bis — r2 was procedural HOLD on
untracked-file visibility, re-ran as r2bis after staging], T3=3 [r1 +
r2 + r3], T4=1 [r1 CLEAN PROCEED 0 findings on first round]) + the T6
**PR-body** review loop running on this commit chain
(see `.codex-review/correlation-hardening-t6-r*.transcript.log` —
class-of-issue: count-narrative + byte-match drift; folds the body
toward reviewer-trace fidelity). 1 task-gate round per task fewer than
PR-B's per-task average (median 2 vs 2.5) — within
`feedback_codex_iteration` 3-6 band lower edge per umbrella §11 + plan
§2 C10 lock. Task transcripts at
`.codex-review/correlation-hardening-t{-1..4}-r{1..3,2bis}.transcript.log` —
glob pattern `r*` matches all (including `r2bis`); PR-body transcripts
under `t6-r*`.

---

## Architecture

### New surfaces

- **Playwright spec** `apps/frontend/tests/e2e/correlation-uat.spec.ts`
  (369 LoC). 5 test cases mapped 1:1 to umbrella spec §3 UAT 1-5:
  - UAT 1 — populated render (caveat banner + both method markers + chart
    caption locale-pinned `effective n` / `period` + 2 Recharts
    `recharts-line-curve` paths + Spearman click round-trip).
  - UAT 2 — < 30 monthly buckets → BE 422 with
    `value_error.insufficient_sample` envelope + `correlation-error`
    branch with locked en copy.
  - UAT 3 — direct GET via Playwright `request` against the seeded
    session: 49-cell `lag_grid` lag[-24..+24], every cell has non-null
    pearson.r + spearman.r + pearson.p_raw + spearman.p_raw + reason: null,
    `interpretation.caveat` + `methodology_url` non-empty.
  - UAT 4 — URL state survives reload (visit with `method=spearman`,
    `page.reload()`, URL keeps method=spearman, post-reload aria-pressed
    + page-level marker flips back).
  - UAT 5 — KO/EN locale toggle: heading + caveat + caption tokens swap;
    EN tokens DISAPPEAR after the swap (catches partial-i18n-render bugs);
    Pearson/Spearman invariant preserved; en re-toggle for trailing test
    isolation.

  Reuses PR #36 T13 provider-state handlers — the spec uses 2 of the 5
  available states, both as exact phrases byte-matching
  `services/api/src/api/routers/pact_states.py:2577-2614`:
  `seeded correlation populated fixture and an authenticated analyst session`
  (UAT 1 / 3 / 4 / 5 — populated render branch) +
  `seeded correlation insufficient_sample 422 fixture and an authenticated analyst session`
  (UAT 2 — empty-state branch). Plan C5 cited catalog as a candidate
  state, but the implementation reads the catalog inline via the
  populated-fixture session cookie (no separate catalog seed needed at
  the E2E layer). Unknown-state fall-through at `pact_states.py:2620-2624`
  makes exact-phrase match mandatory; copy-paste-from-source-of-truth.

  Locale pin per memory `pattern_i18n_pin_in_test_locale` —
  `context.addInitScript` seeds `localStorage.i18nextLng = 'en'` BEFORE
  the first navigation so i18n bootstrap reads English on first mount
  regardless of CI runner navigator default.

- **Perf smoke** `services/api/tests/perf/test_correlation_p95.py`
  (150 LoC). Single `@pytest.mark.perf @pytest.mark.asyncio` test that:
  - Seeds the populated fixture + mints an analyst session via the
    dev-only `/_pact/provider_states` endpoint (exact phrase per C5/C7).
  - Issues 50 sequential `GET /api/v1/analytics/correlation
    ?x=reports.total&y=incidents.total&date_from=2018-01-01
    &date_to=2026-04-30&alpha=0.05` against running uvicorn (default
    `127.0.0.1:8000`; override via `PERF_API_BASE_URL`).
  - Times each request via `time.perf_counter()`.
  - Asserts `numpy.percentile(durations_ms, 95) <= 500.0` per plan C4
    + umbrella §3 NFR-1.
  - On budget exceedance, the diagnostic message includes
    min / median / max / sorted top-3 worst latencies so an oncall can
    distinguish steady-state slowdown from tail outliers without
    re-running the suite.

  **Why running uvicorn, not in-process `ASGITransport`:** the
  integration tests at `services/api/tests/integration/
  test_correlation_route.py` use in-process transport for fast contract
  checks. NFR-1 is a production-shape latency assertion — must include
  uvicorn worker roundtrip + real Postgres + Redis sockets + network hop
  to be meaningful. Plan §C4 explicit ("running uvicorn") + R-C2
  mitigation pin this lock.

- **Perf opt-in gate** `services/api/tests/perf/conftest.py` (67 LoC).
  `pytest_collection_modifyitems` deselects perf-marked tests unless
  `PERF_TEST=1` env var is set. Mirrors the `integration` marker's
  `POSTGRES_TEST_URL` env-var-gate precedent at
  `services/api/pytest.ini:5-9`. Default `uv run pytest` reports the
  test as "deselected" (not "skipped") so the unit-suite output stays
  clean.

- **Vitest spec** `apps/frontend/src/features/analytics/correlation/
  __tests__/CorrelationFilters.test.tsx` (161 LoC, 3 cases). Pins the C6
  catalog-grouping refactor:
  1. Renders `Reports` + `Incidents` section headers with translated
     `en` copy.
  2. Options nest under root-correct group; **shadow rows** whose `id`
     prefix CONFLICTS with `root` (`incidents.legacyReportFamily`
     rooted `reports.published`; `reports.legacyIncidentFamily` rooted
     `incidents.reported`) discriminate `root`-grouping vs `id`-prefix
     grouping. Negative assertions pin both directions per
     `pattern_count_distinct_regression_coverage` (fixtures must
     DIFFERENTIATE correct vs incorrect implementations).
  3. Per-option click regression guard preserves `onChangeX` wiring.

  Locale pin per `pattern_i18n_pin_in_test_locale` —
  `import '../../../../i18n'` + `await i18n.changeLanguage('en')` in
  `beforeEach`.

### Modified surfaces

- `apps/frontend/src/features/analytics/correlation/CorrelationFilters.tsx`
  (236 LoC, was 192). `SERIES_ROOTS` literal-tuple drives stable
  `reports.published` → `incidents.reported` group order. Each axis
  renders `<ul role="listbox">` containing per-root `<ul role="group">`
  partitions. Section headers use new testids
  `correlation-filter-{x|y}-group-{reports|incidents}` and a container
  `*-list` testid for nesting tests. Existing per-option testids
  `correlation-filter-{x|y}-option-{id}` preserved unchanged. Empty-group
  guard: a root with zero catalog matches renders nothing (no header
  without options). **No URL / cache-key / BE-surface impact** — cosmetic
  only per umbrella §11 PR-C lock + §0.1 amendment 7 pickup from PR #36.

- `apps/frontend/src/i18n/en.json` + `ko.json` — 2 new keys
  (`correlation.filters.groupReports`, `correlation.filters.groupIncidents`).
  Both stay OUT of the cross-locale parity invariant allowlist per C9
  lock — they legitimately differ ko vs en (`Reports` ≠ `보고서`).

- `apps/frontend/src/i18n/index.ts` — `Resources` interface extended
  with the 2 new keys.

- `apps/frontend/src/i18n/__tests__/init.test.ts` — parity check key list
  extended with the 2 new keys; both stay OUT of invariant allowlist.

- `apps/frontend/lighthouse/README.md` — 5 locations updated for the 6th
  audit target (`/analytics/correlation?x=reports.total&y=incidents.total`):
  routes table (+1 row), STATES bash array (+1 entry), TARGETS bash
  array (+1 entry), result-layout tree (+1 subdir), prerequisite step
  prose ("All five" → "All six"). **No code changes** — `run-audit.mjs`
  is target-agnostic via `LH_PATH` + `LH_REPORTS_SUBDIR` env vars (see
  `run-audit.mjs:67-78` + `:233` URL concat — query-string TARGET_PATH
  flows cleanly through to `targetUrl = URL_BASE + TARGET_PATH`).

- `services/api/pytest.ini` — `perf` marker registered in the
  `markers =` block (`--strict-markers` is already set, registration is
  mandatory). Description follows the `integration:` template.

- `.github/workflows/ci.yml` — appends a `correlation-perf-smoke` job at
  end. Gated on `if: github.event_name == 'workflow_dispatch'` so it
  ONLY runs on manual trigger (NOT on push / PR) per plan §8 Q-C1 +
  R-C2. The job mirrors the `frontend-e2e` boot pattern (postgres +
  redis services + alembic upgrade + uvicorn boot + `/healthz` poll)
  but skips the FE preview side — perf test calls `/_pact/provider_states`
  directly to seed the fixture, no FE involvement.

### Why query-string seeding for the 6th Lighthouse target

Bare `/analytics/correlation` lands on empty state until X/Y are
selected (Codex T16 pre-merge LOW finding for PR #36). Query string
`?x=reports.total&y=incidents.total` is hydrated by `CorrelationPage.tsx`
`useState` initializer **synchronously** — the populated state renders
before Shell hydration per `pattern_page_local_url_state_route_gate`
(established in PR #36 T10 r1 fold). The audit measures chart-render
performance, not the empty-state-to-populated transition (which would
be a different metric).

---

## Defaults applied (plan §8 Open Questions)

These are the defaults from plan §8; no user override was requested
before T0 dispatch. Each ships verbatim with no §0.1 amendment.

- **Q-C1 — Perf smoke CI cadence:** `workflow_dispatch` (manual trigger)
  only. Cron schedule deferred to a follow-up if NFR-1 regression
  detection becomes a concern. R-C2 mitigation also pins this — cold-start
  CI runner flake risk is high enough that auto-on-every-PR would
  produce false-positive failures.
- **Q-C2 — Lighthouse 6th target seeding:** query-string
  `?x=reports.total&y=incidents.total`. T1 base verified
  `run-audit.mjs:67-78` + `:233` URL concat handles query-string targets
  cleanly.
- **Q-C3 — Q1 catalog grouping label copy:** `Reports` / `Incidents` (en)
  + `보고서` / `사건` (ko) — matches existing `shell.nav.reports` +
  `shell.nav.incidents` copy. Minimal copy.
- **Q-C4 — Perf smoke sample-size N:** 50 sequential requests per
  umbrella §3 NFR-1 + UAT 6.

---

## Plan §0.1 amendments (1 total, recorded in `docs/plans/pr37-correlation-hardening.md` §9)

Per `pattern_plan_vs_impl_section_0_1_amendments`. None of these
changed a B-row policy invariant; the entry is a plan-vs-codebase
factual drift fix surfaced at Codex T-1 r1 plan review.

1. **T-1 r1 (2026-05-09 — Codex T-1 r1 fold):** 8 findings folded
   together as class-of-issue (factual drift between plan claims and
   the codebase / umbrella spec) per
   `pattern_sweep_class_when_codex_finds_one`:
   - **HIGH 1** — C6 + T2 + §1 Goal grouped by `s.id` prefix; corrected
     to group by `s.root` literal value (2-value enum at
     `apps/frontend/src/lib/api/schemas.ts:692`; `id` is opaque per
     umbrella §2.2).
   - **HIGH 2** — C5 + T3 named non-existent provider states; corrected
     to exact phrases at `services/api/src/api/routers/pact_states.py:
     2565-2620`. Unknown-state fall-through at `:2620-2624` makes
     exact-phrase match mandatory.
   - **HIGH 3** — C4 + T4 perf opt-in mechanism wrong. Marker config
     goes in `services/api/pytest.ini` (existing markers section,
     `--strict-markers` is already set), NOT `pyproject.toml`. Default-
     skip uses `pytest_collection_modifyitems` in conftest checking
     `PERF_TEST=1` env var — mirrors the existing `integration` marker's
     `POSTGRES_TEST_URL` skip-condition precedent.
   - **MED 1** — File inventory: `CorrelationFilters.test.tsx` was
     listed as modified but doesn't exist on `main@bfa2374`. Moved to
     "new" + C8 lock rewritten. Final inventory: 6 new + 7 modified =
     13 files; at C2's 50%-overage ceiling.
   - **MED 2** — R-C5 mitigation pre-authorized scope expansion
     ("fold the fix into PR-C"). Rewritten to BLOCK PR-C + file separate
     hotfix PR if T13 verify reveals real failure. Verification PR is
     the auditor, not the patcher.
   - **MED 3** — T4 + T5 dependencies on T3 spurious. Both deps trimmed
     to T0 so T1/T2/T3/T4/T5 are genuinely parallelizable post-T0.
   - **LOW 1** — T0 inventory cited non-existent
     `services/api/tests/contract/conftest.py`; corrected to cite the
     actual existing precedent: `tests/contract/test_openapi_snapshot.py`
     + `pytest.ini:5-9` (integration marker precedent).
   - **LOW 2** — AC #10 conflated vitest + contract + build verification
     under T2; split into 4 rows (#10 vitest → T2; #11 contract → T7;
     #12 build → T7; #13 OpenAPI snapshot → T7). Total AC rows: 14 → 16.

### Plan-vs-impl notes (sub-amendment — no §0.1 entry, transparent reviewer-visible deltas)

These are operational notes that did NOT trigger a §0.1 amendment per
`pattern_plan_vs_impl_section_0_1_amendments` ("plan-vs-impl" is for
deviations from policy invariants, not for adjacent-band sizing). Both
are within explicit plan-locked tolerance bands.

- **T2 vitest count:** plan AC #10 said `858/858 + 2 new = 860/860`;
  shipped `858/858 + 3 new = 861/861`. The +1 case is the
  shadow-row discrimination test that pins `root`-grouping vs `id`-
  prefix grouping per `pattern_count_distinct_regression_coverage` —
  added during T2 r1 Codex fold for fixture rigor. Plan C6 says "at
  least 2 cases" — within spec. AC #10 numerics in this body have been
  refreshed to `861/861` accordingly.
- **T4 file count:** plan §3 said "no `__init__.py` per
  `pitfall_pytest_rootdir`"; shipped
  `services/api/tests/perf/__init__.py` (empty, matches sibling
  `tests/contract/__init__.py` + `tests/integration/__init__.py` +
  `tests/unit/__init__.py` convention). Plan T-1 r1 MED 1 collapsed the
  i18n pair (`en.json` + `ko.json`) to one logical change, yielding
  "6 new + 7 modified = 13 files" by effective-code-file count. The raw
  `git diff --name-status main..HEAD` count at T4 head is **6 new + 8
  modified = 14 files** (the 8th modified is
  `apps/frontend/src/i18n/__tests__/init.test.ts`, a 2-line key-list
  extension folded under the i18n pair logical change). T6 adds
  `correlation-hardening-body.md` (NEW) bringing the raw total to
  **7 new + 8 modified = 15 files** at the T6 head. Within the C2
  50%-overage band ceiling (≤ 19 files for the 13-file effective-code
  baseline; ≤ 21 files for the 14-file raw baseline).

---

## Verification

### ✅ Completed locally

| Layer | Count | Note |
|:---|---:|:---|
| FE vitest | **861/861** pass across 97 files | Was 858 baseline at PR #36 merge → 861 GREEN at T2 head (+3 in `CorrelationFilters.test.tsx`); no regressions since |
| FE Pact consumer | **26/26** pass | Inherited from PR #36; no PR-C consumer change |
| FE production build | green | `corepack pnpm run build` (tsc -b + vite); root tsconfig has `files=[]` so `tsc --noEmit` is a no-op — see `feedback_real_build_check` |
| OpenAPI snapshot | empty diff | No PR-C BE behavior change (perf test calls existing endpoint unchanged); CI drift guard from PR #36 stays green |
| Pytest unit suite | 807 passed / 5 skipped / 1 deselected | The 1 deselected is `test_correlation_p95.py` (gate fires correctly when `PERF_TEST` unset). The 1 pre-existing failure `test_pact_producer_verifies_consumer_contracts` requires `PACT_PROVIDER_BASE_URL` (intentional fail-loud per `pitfall_xfail_green_on_ci`); does NOT run in the unit-loop CI config |
| Pytest collection gate | passes both directions | `uv run pytest --collect-only tests/perf` → "no tests collected (1 deselected)" (gate fires); `PERF_TEST=1 uv run pytest --collect-only -m perf tests/perf` → "1 test collected" (gate releases) |

Run locally:

```bash
cd apps/frontend
corepack pnpm vitest run --reporter=basic    # expect 861 pass
corepack pnpm run test:contract              # expect 26 pass
corepack pnpm run build                      # expect green

cd ../../services/api
uv run pytest tests/contract/test_openapi_snapshot.py -q   # expect 4 pass
uv run pytest --collect-only tests/perf                    # expect 0 collected, 1 deselected
PERF_TEST=1 uv run pytest --collect-only -m perf tests/perf  # expect 1 collected
```

### 🟡 Pending (CI / user-side)

- **T3 live Playwright E2E** — UAT 1-5 against host-hybrid stack. Runs
  in CI's `frontend-e2e` job (`.github/workflows/ci.yml:30-159`)
  automatically picks up the new spec via `pnpm test:e2e`. Not run
  locally yet; first green CI run lands at T7 push.
- **T4 live perf smoke** — `correlation-perf-smoke` job on
  `workflow_dispatch` only. Reviewer or maintainer triggers manually
  via the Actions UI after merge (or before, on this branch); first
  invocation captures the wall-clock p95 number for NFR-1
  acceptance.
- **T5 live `pnpm pact:provider` replay** — backfills PR #36's deferred
  T13 verification gate. User-side procedural step (requires Docker
  triad). Expected: `Verified pact (5 + 21 = 26 interactions) ✓`.
  Transcript captured at
  `.codex-review/correlation-hardening-t5-pact-verify.transcript.log`
  (gitignored). Plan §6 testing-strategy line cites the run.
- **Lighthouse 6-target loop run** — informational only per existing
  harness contract (`run-audit.mjs:22-24`). Reviewer or maintainer
  runs `apps/frontend/lighthouse/README.md` for-loop against the host
  triad after merge; produces `apps/frontend/lighthouse/reports/
  correlation/SUMMARY.md` + 6 JSONs (3 light + 3 dark).
- ~~**CI green on push.**~~ ✅ **12/12 SUCCESS + 1 SKIPPED** at PR
  the latest CI-witnessed SHA at body-write-time: `7d6f074` (T7
  PR-as-diff r1 fold; `mergeStateStatus: CLEAN`, `mergeable:
  MERGEABLE`). Subsequent fold commits will re-run CI; the SHA in
  this paragraph is the most recent CI-green head at write-time and
  will be re-synced on the next post-CI body sync if a fold lands.
  Surface for this branch is 12 PR-event checks (not 24) because
  `chore/*` is outside the `on.push.branches: ["main", "feat/**"]`
  filter at `.github/workflows/ci.yml:5` — only the `pull_request`
  event fires; see AC #14. The new `correlation-perf-smoke` job is
  the 1 SKIPPED (`workflow_dispatch` only) and NOT counted toward
  AC #14. First CI run on PR #37 head `4fe0ccd` surfaced 2 real
  test failures in the new `correlation-uat.spec.ts` (UAT 2 + UAT 5)
  that escaped local validation per `phase_status.md` "T3 live
  Playwright run NOT executed locally"; both fixed in T7 fix #1
  (`f917165`) + T7 fix #2 (`55c4929`). Net cost: 2 fix commits +
  CI re-run, no body-side scope expansion.
- **Final external Codex review (PR-as-diff loop)** per
  `pattern_codex_body_review_loop` + `feedback_codex_iteration` 3-6
  rounds typical. LOWs at the PASS gate are fold-or-skip per
  `feedback_codex_iteration` + `pattern_no_cosmetic_pad_on_green_draft`.

### Acceptance criteria (per plan §7)

| # | Criterion | Status |
|:---:|:---|:---:|
| 1 | UAT 1 — analyst login → correlation page → reports.total × incidents.total → both methods (Pearson + Spearman) render with p-values + caveat banner + lag chart [-24, +24] | ✅ (T3 — `frontend-e2e` CI job pass at PR #37 head `7d6f074`, 7.7s — CI also green on prior heads `55c4929` + `30f87e9`) |
| 2 | UAT 2 — < 30 monthly buckets → empty state with locked copy "표본이 부족합니다 (최소 30개월 필요)" / "Insufficient sample" | ✅ (T7 fix #1 — first-CI surfaced DB-accumulation bug; INSUFFICIENT_QS narrows query to 2026-05..2027-12 to dodge POPULATED's 2018-01..2026-04 coverage; CI pass since `f917165` through `7d6f074`) |
| 3 | UAT 3 — direct GET to `/api/v1/analytics/correlation?...` returns both methods at lag 0 + full lag scan + `interpretation.caveat` + `interpretation.methodology_url` | ✅ (T3 — CI pass at `7d6f074`, 4.1s) |
| 4 | UAT 4 — URL state survives reload | ✅ (T3 — CI pass at `7d6f074`, 5.2s) |
| 5 | UAT 5 — KO / EN locale toggle swaps all chart labels including caveat banner | ✅ (T7 fix #1 + #2 — UserMenu open + dropdown-close-via-Escape after each toggle click; Radix `<DropdownMenu>` aria-hidden focus-trap blocks role queries while menu is open; CI pass since `55c4929` through `7d6f074`) |
| 6 | UAT 6 / NFR-1 — p95 ≤ 500 ms over 50 sequential requests | 🟡 (T4 smoke shipped + opt-in gate verified locally; live wall-clock p95 measured at first `workflow_dispatch` run — non-blocking per plan §8 Q-C1 + R-C2) |
| 7 | Lighthouse 6-target loop runs cleanly (`reports/correlation/SUMMARY.md` exists; reviewer accepts scores) | 🟡 (T1 README updated; user-side audit run — informational only per `run-audit.mjs:22-24` harness contract) |
| 8 | Q1 catalog grouping shows `[ Reports ]` / `[ Incidents ]` headers with options nested correctly | ✅ (T2 — vitest 861 GREEN with discriminating shadow-row test; CI `frontend` vitest job pass at `7d6f074`) |
| 9 | T13 live `pnpm pact:provider` replay 5/5 verify + legacy 21 still pass; transcript captured | 🟡 (T5 — user-side procedural backfill; pact-ruby per-interaction reset model means contract-verify CI job already independently verified each interaction) |
| 10 | vitest 861/861 GREEN (was 858/858 + 3 new from T2; +1 vs plan's `+2` baseline — within C6 "at least 2 cases" lock) | ✅ (locally + CI `frontend` job pass at `7d6f074`) |
| 11 | Pact contract 26/26 GREEN preserved (no PR-C change to consumer interactions) | ✅ (CI `frontend` `pnpm test:contract` step pass at `7d6f074`) |
| 12 | FE production build green (`pnpm run build` exits 0) | ✅ (CI `frontend` `pnpm run build` step pass at `7d6f074`) |
| 13 | OpenAPI snapshot diff at PR head is empty | ✅ (CI `contract-verify` job pass at `7d6f074` — no PR-C BE behavior change) |
| 14 | Branch CI green on all 12 PR-event checks (default surface). The `chore/p3.s3-correlation-hardening` branch name is OUTSIDE the `on.push.branches: ["main", "feat/**"]` filter at `.github/workflows/ci.yml:5`, so the push event does NOT fire on this branch — only the `pull_request` event runs. PR #36's branch matched `feat/**` and saw the 12 × 2 = 24 surface; PR-C's `chore/*` branch sees the 12 PR-event checks only. The perf job is `workflow_dispatch` only and NOT counted toward this AC. | ✅ (12/12 PR-event SUCCESS + 1 SKIPPED `correlation-perf-smoke` at `7d6f074` — also at prior heads `55c4929` + `30f87e9`; `mergeStateStatus: CLEAN`, `mergeable: MERGEABLE`) |
| 15 | Final external Codex review reports no unresolved CRITICAL/HIGH | 🟡 (PR-as-diff at T7-T8) |
| 16 | PR body present at `docs/plans/pr37-correlation-hardening-body.md`; plan present at `docs/plans/pr37-correlation-hardening.md` | ✅ (renamed at T7 push commit; PR #37 confirmed via `gh pr list`) |

---

## What's NOT in this PR

- **Power-user any-two-series API** (umbrella §10.1 — out of slice-3 scope
  entirely).
- **Quarterly / yearly granularity** (§10.2 — out of scope).
- **F-2 / F-4 / F-5 downstream consumers** (§10.3-10.5 — out of scope).
- **Cross-pair correction** (§10.6 — out of scope).
- **Lazarus.day parity check** — backlog; tracked in `phase_status.md`
  Pending follow-ups.
- **DESIGN.md token migration** (PR #35 deferral — hardcoded SVG colors
  in `ActorNetworkGraph.tsx` → DESIGN.md token references). Backlog.
- **d3 SimulationNodeDatum type cleanup** (PR #35 deferral). Backlog.
- **Continuous animation of d3-force** (PR #35 deferral). Backlog.
- **Click-to-drill from graph node into `/actors/:id` filtered view**
  (PR #35 deferral). Backlog.
- **PR #36 T14 dev-triad smoke backfill.** Codex T16 pre-merge round
  adjudicated SAFE TO MERGE without it; backfill remains optional. Not
  inside PR-C scope per plan §1 non-goals.

---

## Reviewer test plan

```bash
# Stack
docker compose up -d db cache keycloak otel-collector
set -a && source envs/api.env.local && set +a
(cd services/api && uv run --all-extras python ../../scripts/_run_api_dev.py)
(cd apps/frontend && npx --yes pnpm@9 dev)

# Test suites
(cd apps/frontend && corepack pnpm vitest run)            # expect 861 pass
(cd apps/frontend && corepack pnpm run test:contract)     # expect 26 pass
(cd apps/frontend && corepack pnpm run build)             # expect green
(cd services/api && uv run pytest tests/contract/test_openapi_snapshot.py -q)  # expect 4 pass

# Perf gate (off by default)
(cd services/api && uv run pytest --collect-only tests/perf)
# expect: "no tests collected (1 deselected)"

(cd services/api && PERF_TEST=1 uv run pytest --collect-only -m perf tests/perf)
# expect: "1 test collected"

# Live perf smoke (needs running uvicorn + populated DB; uses _pact/provider_states to seed)
(cd services/api && PERF_TEST=1 uv run pytest -m perf tests/perf -q)
# expect: "1 passed" with p95 ≤ 500 ms

# E2E (host-hybrid stack already up)
(cd apps/frontend && corepack pnpm exec playwright test correlation-uat.spec.ts)
# expect: 5 passed (UAT 1..5)
```

Browser at `http://localhost:5173`:

1. Log in as `analyst@dev.local` / `test1234` → land on `/dashboard`.
2. Click `Correlation` top-nav → `/analytics/correlation` renders.
3. Open the `X` dropdown → see `[ Reports ]` and `[ Incidents ]` section
   headers; series options nest under the correct group based on each
   series' `root` field.
4. Pick `reports.total` for X and `incidents.total` for Y → populated
   state with 49-point lag chart, both Pearson + Spearman series visible,
   caveat banner, locale-pinned `effective n` / `period` chart caption.
5. Toggle KO / EN — every visible string swaps including the new
   `[ 보고서 ]` / `[ 사건 ]` headers.
6. URL hydrates with `?x=...&y=...&method=...`; reload → state survives.

Lighthouse audit (informational, post-merge or pre-merge ad-hoc):

```bash
cd apps/frontend/lighthouse
# follow README.md prerequisites; STATES + TARGETS arrays now have 6 entries
# resulting reports/ tree gains correlation/ subdir
```

Manual `workflow_dispatch` perf run (post-merge or on this branch):

```
GitHub → Actions → "DPRK CTI CI" → Run workflow → branch=chore/p3.s3-correlation-hardening
```

Look for the `correlation-perf-smoke` job in the run summary — it boots
postgres + redis + uvicorn, seeds the populated fixture via
`_pact/provider_states`, runs 50 sequential GETs, asserts p95 ≤ 500 ms.

API surface (via dev triad, optional sanity checks):

```bash
curl -b "session=<cookie>" 'http://localhost:8000/api/v1/analytics/correlation/series' | jq .
curl -b "session=<cookie>" 'http://localhost:8000/api/v1/analytics/correlation?x=reports.total&y=incidents.total' | jq '.lag_grid | length'  # expect 49
```

---

## Decision log highlights

- **Group by schema `root`, not `id` prefix** (Codex T-1 r1 HIGH 1).
  `id` is opaque per umbrella §2.2 + the schema doc comment at
  `apps/frontend/src/lib/api/schemas.ts:683`. `root` is the canonical
  2-value enum at `:692`. Test fixtures include shadow rows whose `id`
  prefix CONFLICTS with `root` to discriminate the two implementations
  per `pattern_count_distinct_regression_coverage`.
- **Provider-state strings use exact phrases from the BE handler**
  (Codex T-1 r1 HIGH 2). Unknown states fall through with session-only
  seeding at `pact_states.py:2620-2624` — exact-phrase match is
  mandatory; copy-paste from the source-of-truth file.
- **Perf opt-in gate via `pytest_collection_modifyitems` checking
  `PERF_TEST=1`, not `@pytest.mark.skipif` decorator** (Codex T-1 r1
  HIGH 3). Mirrors the existing `integration` marker's
  `POSTGRES_TEST_URL` env-var-gate precedent at `pytest.ini:5-9`.
  `--strict-markers` is already set, so marker registration in
  `pytest.ini` is mandatory.
- **Perf job on `workflow_dispatch` only, NOT every PR** (plan §8 Q-C1
  + R-C2). Cold-start CI runner flake risk per
  `pitfall_pact_v3_ci_cold_start_race` is high enough that auto-on-PR
  would produce false-positive failures. Manual trigger keeps the perf
  signal credible.
- **Running uvicorn for perf smoke, not in-process `ASGITransport`**
  (plan §C4). NFR-1 is a production-shape latency assertion — must
  include uvicorn worker roundtrip + real Postgres + Redis sockets +
  network hop to be meaningful.
- **Query-string hydration for the 6th Lighthouse target** (plan §C3).
  Bare `/analytics/correlation` lands on empty state. Query string
  hydrates synchronously via `useState` initializer per
  `pattern_page_local_url_state_route_gate` (PR #36 T10 r1) — audit
  measures chart-render perf, not the empty-to-populated transition.
- **R-C5 hotfix-PR over fold-into-PR-C** (Codex T-1 r1 MED 2). If T13
  live verify reveals real failure, PR-C BLOCKs + a separate hotfix PR
  fixes PR #36's T13 handlers; PR-C rebases on the hotfix's merge
  commit and re-runs T5. Verification PR is the auditor, not the
  patcher; conflating roles inverts the audit trail.
- **Shadow-row discrimination test for the C6 grouping refactor**
  (Codex T2 r1 MED). Fixtures with id-prefix-matches-root would not
  discriminate a faulty `id.startsWith(...)` implementation from a
  correct `s.root === 'reports.published'` one. Two shadow rows
  (`incidents.legacyReportFamily` rooted reports.published;
  `reports.legacyIncidentFamily` rooted incidents.reported) + 4
  negative assertions per
  `pattern_count_distinct_regression_coverage`.
- **Per-cell `p_raw` non-null assertions in UAT 3** (Codex T3 r2 MED).
  Comment claimed per-cell p-value checks but loop only had r/reason;
  `p_raw` was anchored only at lag 0. Folded by moving `p_raw`
  non-null assertions into the per-cell loop so non-zero-lag p-value
  regressions are caught. Lag-0 block kept as a presence-only anchor.
- **`__init__.py` for `tests/perf/` matches sibling-dir convention**
  (T4 deviation from plan §3 inventory). `tests/contract/`,
  `tests/integration/`, `tests/unit/` all have `__init__.py`. Plan
  §3's "no `__init__.py` per `pitfall_pytest_rootdir`" was based on a
  different parent-dir convention; sibling consistency is the right
  call here. Recorded in this body's "Plan-vs-impl notes" subsection;
  not a §0.1 amendment per `pattern_plan_vs_impl_section_0_1_amendments`
  (within C2 50%-overage band).

---

## Pre-merge checklist

- [x] FE vitest 861 / contract 26 / FE build green (locally)
- [x] OpenAPI snapshot diff empty (no PR-C BE behavior change)
- [x] Pytest collection gate verified both directions (deselect-by-default + release-on-`PERF_TEST=1`)
- [x] EN + KO i18n strings present for the 2 new keys (parity check enforces drift guard; not in invariant allowlist)
- [x] No `data-testid` removals; no OpenAPI line removals; URL_STATE_KEYS unchanged
- [x] Per-option `correlation-filter-{x|y}-option-{id}` testids preserved unchanged (cosmetic-only refactor)
- [x] Plan doc (`docs/plans/pr37-correlation-hardening.md`) + PR body (`docs/plans/pr37-correlation-hardening-body.md`) committed; renamed from `correlation-hardening{,-body}.md` at T7 push per `plan_doc_convention`
- [ ] T5 — Live `pnpm pact:provider` replay 5/5 + legacy 21 verify (user-side, requires Docker stack); transcript captured
- [ ] T1 — Local Lighthouse 6-target audit run produces `reports/correlation/SUMMARY.md` (informational, optional)
- [ ] Push DRAFT; CI 12 PR-event checks green (push event does NOT fire on `chore/**` branches per `.github/workflows/ci.yml:5` filter — only the `pull_request` event runs, so AC #14's surface is 12 not 24)
- [ ] First `correlation-perf-smoke` `workflow_dispatch` run captures wall-clock p95 ≤ 500 ms
- [ ] Final external Codex PR-as-diff review reports no unresolved CRIT/HIGH (per `feedback_codex_iteration`)

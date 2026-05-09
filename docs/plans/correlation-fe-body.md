# Phase 3 Slice 3 PR-B — D-1 Correlation FE Visualization

**Scope:** FE-only. New `/analytics/correlation` route, 5 leaf components, 2
react-query hooks, 7 zod schemas, 5 Pact consumer interactions, page-class
runtime mechanism, full ko + en i18n. **Zero BE changes** — consumes the
D-1 primitive shipped in PR #28.

**Why:** PR #28 landed the BE side of the D-1 correlation primitive
(`/analytics/correlation/series` catalog + `/analytics/correlation` lag
scan with the umbrella's locked 6-field × 49-cell DTO). PR #31 landed the
DESIGN.md v2 page-class taxonomy. This PR is the user-visible side: an
analyst-role user can pick two series from the catalog, render the lag
scan with both Pearson + Spearman, see the typed warning chips, and read
the "correlation ≠ causation" caveat banner. Closes the umbrella spec's
PR-B (D-1 visualization) per
`docs/plans/phase-3-slice-3-correlation.md` §11.

**Base:** `main` directly (current HEAD `5b42c6e` from PR #35). No stack;
PR #28 (BE primitives) and PR #31 (design contract) are both already on
main. No base-flip risk per `pitfall_stacked_pr_merge_base_flip`.

**Branch:** `feat/p3.s3-correlation-fe`.

**Plan:** `docs/plans/correlation-fe.md` v1.0 (will rename to
`pr{N}-correlation-fe.md` after `gh pr list` confirms the assigned PR
number).

---

## What lands (22 commits, ~20.2K insertions / 50 deletions across 50 files)

The bulk of the line count is the regenerated `contracts/pacts/frontend-dprk-cti-api.json`
(+14,722 lines on its own — the 49-cell × 6-field × 2-method × 3 happy
interactions with explicit per-cell positional matchers per
`pattern_pact_explicit_array_for_length_pin`; non-Pact code change is
~5,500 lines including this plan + body).

| Commit | Phase | Change |
|:---|:---|:---|
| `45e6f8e` | T-1 (plan) | docs(plan): correlation-fe v1.0 — refresh against main@5b42c6e + Codex r1-r4 folds |
| `0fd6ba0` | T0 | feat: correlation-fe T0 — page-class runtime mechanism (9-entry manifest + `data-page-class` attribute on every routed container) |
| `1ca4789` | T2 | feat: correlation-fe T2 — 7 zod schemas for D-1 correlation DTOs |
| `64803a2` | T3 | feat: correlation-fe T3 — endpoint helpers (`getCorrelationCatalog` / `getCorrelation`) + 422 envelope schema |
| `2c04a3c` | T4 | feat: correlation-fe T4 — query keys for catalog + primary (5-tuple isomorphic to BE Redis key) |
| `abfcaf2` | T5 | feat: correlation-fe T5 — `useCorrelationSeries` + `useCorrelation` hooks |
| `997b1d5` | T6 | docs(plan): correlation-fe T6 §0.1 amendment — OpenAPI regen command (BE-side flow, FE script does not exist) |
| `67ba55b` | T7 base | test: correlation-fe T7 — RED component tests + 5 NotImplementedError stubs |
| `2c5953f` | T7 r1 | test: correlation-fe T7 r1 fold — urlState catalog fixture + B5 5-key write-back |
| `e691210` | T7 r2 | test: correlation-fe T7 r2 fold — strengthen urlState write-back assertions |
| `3f127c8` | T7 r3 | test: correlation-fe T7 r3 fold — final-settled-href pattern across all write-back tests |
| `8349a94` | T8 base | test: correlation-fe T8 — 5 Pact consumer interactions per umbrella §7.6 |
| `517d6b6` | T8 r1 | test: correlation-fe T8 r1 fold — 49-cell length-pin + literal loc + warning equal() |
| `b7373c5` | T9 base | feat: correlation-fe T9 — components GREEN (4-state render + URL state + method toggle) |
| `db6e23a` | T9 r1 | test: correlation-fe T9 r1 fold — Codex CRITICAL chart palette + 2 MEDIUM date-input + URL re-hydrate |
| `292e745` | T10 base | feat: correlation-fe T10 — router mount + Shell nav + command palette + page-class manifest |
| `ec7efd9` | T10 r1 | test: correlation-fe T10 r1 fold — Codex CRITICAL `useFilterUrlSync` route gate + MEDIUM nav overflow + LOW comment drift |
| `3e1abd1` | T10 r2 | test: correlation-fe T10 r2 fold — strip historical theme reference from SearchResultsSection comment |
| `a53663c` | T11 base | feat: correlation-fe T11 — i18n keys for 5 components + parity check |
| `83687e7` | T11 r1 | test: correlation-fe T11 r1 fold — Codex 3 LOWs (T9→T11 docstring header drift) |
| `1186930` | T12 base | docs: correlation-fe T12 — PR body draft staged at correlation-fe-body.md |
| _(this commit)_ | T12 r1 | docs: correlation-fe T12 r1 fold — Codex 2 CRITICAL (Q1+Q4 §8 default deviations) + MED amendment count + LOW round count |

28 Codex review rounds across T0..T11 (T0=3, T1=2, T2=4, T3=1, T4=1,
T5=1, T6=2, T7=4, T8=3, T9=2, T10=3, T11=2 — most tasks within
`feedback_codex_iteration` 3-6 typical band; the 1-round tasks were
mechanical and Codex returned CLEAN PROCEED on the first pass).
Transcripts at `.codex-review/correlation-fe-t{0..11}-r{...}.transcript.log`.

---

## Architecture

### New surfaces

- **Route:** `/analytics/correlation` (single new route; first
  analytics-namespaced FE route — there was no `/analytics/*` parent
  surface on `main@5b42c6e`).
- **Components** under `apps/frontend/src/features/analytics/correlation/`:
  - `CorrelationPage.tsx` — route container, 4-state render orchestrator.
  - `CorrelationFilters.tsx` — X/Y series pickers (custom disclosure
    dropdowns) + date-from/to inputs (`DraftDateInput` with ISO regex
    commit gate).
  - `CorrelationCaveatBanner.tsx` — sticky "correlation ≠ causation"
    banner, dismiss-once-per-tab via sessionStorage.
  - `CorrelationLagChart.tsx` — recharts `LineChart` 480×240 with both
    Pearson + Spearman series, active-method opacity highlight.
  - `CorrelationWarningChips.tsx` — one chip per warning, 6 codes from
    CONTRACT.md §2 mapped 1:1 to `correlation.warnings.<code>` i18n keys.
- **Hooks:**
  - `useCorrelationSeries()` — catalog, `staleTime: Infinity`.
  - `useCorrelation(x, y, dateFrom, dateTo, alpha)` — primary, 5-min
    `staleTime` per umbrella NFR-1 + §8.7 lock; `enabled: x && y`.
- **Schemas** (zod, `.strict()` everywhere) in `apps/frontend/src/lib/api/schemas.ts`:
  - `correlationSeriesItemSchema` / `correlationCatalogResponseSchema`
  - `correlationCellMethodBlockSchema` / `correlationLagCellSchema`
  - `correlationWarningSchema` / `correlationInterpretationSchema`
  - `correlationResponseSchema`
- **Endpoint helpers** in `apps/frontend/src/lib/api/endpoints.ts`:
  - `getCorrelationCatalog()` / `getCorrelation(...)` — match the 17
    sibling `get*` / `list*` helpers (per §0.1 amendment T3).
- **Query keys** in `apps/frontend/src/lib/queryKeys.ts`:
  - `analyticsCorrelationCatalog()` (3-tuple) /
    `analyticsCorrelation(x, y, dateFrom, dateTo, alpha)` (7-tuple
    isomorphic to BE Redis cache key
    `correlation:v1:{x}:{y}:{date_from}:{date_to}:{alpha}` per umbrella
    §7.5).
- **Page-class runtime mechanism (T0):** `apps/frontend/src/lib/pageClass.ts`
  exports `PageClass` (5-element union) + typed `PAGE_CLASS_BY_ROUTE`
  manifest (10 entries post-merge); every routed container carries
  `data-page-class="..."` and `routes/__tests__/pageClass.test.tsx`
  enforces bi-directional manifest ↔ DOM ↔ DESIGN.md table consistency.
- **Shell + command palette wiring (T10):** `NAV_ITEMS` 4 → 5 (new
  `Correlation` entry); `COMMAND_IDS` 6 → 7 (`nav.correlation`);
  `CommandPaletteButton` `NAV_PATHS` += `/analytics/correlation`;
  `pageClass.ts` manifest 9 → 10.

### URL state surface

5 page-local keys (`x`, `y`, `date_from`, `date_to`, `method`) via the
correlation page's own `useState` initializer + `replaceState` write-back.
**Page-local URL state is route-gated against the global
`useFilterUrlSync` emit** (per `pattern_page_local_url_state_route_gate`,
established this PR): without route-scoping, opening
`/analytics/correlation?x=A&y=B&method=spearman` would have Shell mount
→ hydrate → emit-with-default-globals → strip x/y/method from the
address bar. Fold = `CORRELATION_PATH` constant + `isPageLocalUrlState`
predicate short-circuit on emit (4-line addition). The encoder is
unchanged so the 45 existing `useFilterUrlSync` tests stay green.

### i18n surface

27 keys under a new top-level `correlation` namespace in `ko.json` +
`en.json` (page / methodToggle / method / state / filters / caveat /
chart / warnings). Cross-locale parity invariant allowlist: 3 keys
identical across locales — `correlation.method.pearson` ("Pearson"),
`correlation.method.spearman` ("Spearman"), and
`correlation.filters.datePlaceholder` ("YYYY-MM-DD") — scientific method
names + ISO 8601 format token. The remaining 24 keys MUST differ ko vs en
(parity test enforced via `i18n/__tests__/init.test.ts`).
`CorrelationWarningChips` uses `t(\`correlation.warnings.${w.code}\`,
{ defaultValue: w.message })` so an unknown future BE warning code
renders the BE-supplied message rather than a raw key string.

---

## Defaults applied (umbrella §8 Open Questions)

These are the defaults from the plan §8; no user override was requested
before T2 dispatch. Two §8 defaults were adjusted at T9 for
implementation-vs-plan alignment (Q1 + Q4) and recorded as plan §9
amendments — see "Plan §0.1 amendments" below.

- **Q1 — Catalog dropdown (deviation from §8 default):** plan §8 Q1
  default said "flat dropdown **grouped by root via section headers**";
  T9 ships flat **ungrouped** (`catalog.map(...)` with no
  `[ Reports ]` / `[ Incidents ]` headers). Section grouping is purely
  cosmetic — no URL, cache-key, test-contract, or BE-surface impact.
  Layered in additively in PR-C hardening or a small follow-up PR.
  Recorded in plan §9 amendment (T9 — Q1 catalog dropdown grouping
  deferred).
- **Q2 — Default date window:** empty URL → BE-resolved window
  (`min(reports.published, incidents.reported)` server-side per
  `analytics_correlation.py:219-225`). The BE-resolved dates are echoed
  back in the 200 response and *displayed* in the chart caption, but
  never back-propagated into URL state — that would break
  shareable-URL determinism for the empty-date case.
- **Q3 — Banner dismiss:** sessionStorage scoped per-tab. New tab →
  banner reappears. Verified end-to-end under happy-dom 20.9.0.
- **Q4 — alpha (deviation from §8 default wording):** plan §8 Q4
  default said "FE always sends **without** `alpha` and the BE applies
  its 0.05 default"; this contradicted §B3 hook signature
  (`useCorrelation(x, y, dateFrom, dateTo, alpha)` — 5 positional args
  including alpha) AND §7.5 cache-key isomorphism (BE Redis key
  `correlation:v1:{x}:{y}:{date_from}:{date_to}:{alpha}` — alpha is
  in the BE key). T9 implementation supplies the literal `0.05` from
  `const ALPHA = 0.05` in `CorrelationPage.tsx:60`, threads it through
  the hook → query-key → endpoint helper → URL query string so
  the FE React Query cache slot is isomorphic to the BE Redis slot.
  Effective §8 Q4 default reads as "alpha not surfaced in the filter
  UI; hook always supplies the literal 0.05 for cache-key isomorphism."
  Recorded in plan §9 amendment (T9 — Q4 alpha exposure cache-key
  isomorphism).

---

## Plan §0.1 amendments (7 total, recorded in `docs/plans/correlation-fe.md` §9)

Per `pattern_plan_vs_impl_section_0_1_amendments` — none of these
changed a B-row policy invariant; all are plan-vs-impl wording
alignments surfaced during implementation or PR-body review:

1. **T2 r2** — §5 risk row attributed error-envelope schema to T2; §4
   T3 row owns it. Reworded.
2. **T3** — Helper names. Plan said `fetchCorrelation*` matching
   "the existing `fetchAttackMatrix` shape", but actual sibling is
   `getAttackMatrix` (16 of 17 helpers use `get*` / `list*`). Renamed
   to `getCorrelation*` to match sibling convention.
3. **T6** — OpenAPI regen command. Plan cited a non-existent
   `pnpm openapi:check` script; canonical flow is BE-side (`uv run python
   ../../scripts/regenerate_openapi_snapshot.py` + `pytest
   tests/contract/test_openapi_snapshot.py`).
4. **T7 (Q3 banner storage)** — §5 risk row mitigated to localStorage +
   `<session_uuid>`; §8 Q3 is sessionStorage. §5 corrected per
   `pattern_plan_section_precedence_4_normative_5_descriptive`.
5. **T8 LoC + interaction count + 49-cell length-pin** — Single
   combined entry. §B7 said `+~250 LoC`; actual T8 base was `+2022
   LoC` (test +614 / pact JSON +1409) and the 49-cell explicit-array
   length-pin was a Codex T8 r1 CRITICAL fold (`eachLike` generates
   `min: 1`; `arrayContaining` doesn't pin total length; both miss
   the umbrella §4.4 + BE pydantic + FE Zod 49-cell lock at
   provider-verify time). Pact-interaction count delta `21 → 26` (+5),
   not `25 → 30` (overcount from `grep -c '"description"'`). New memory
   anchor recorded: `pattern_pact_explicit_array_for_length_pin`.
6. **T9 — §8 Q4 alpha exposure (Codex T12 r1 CRITICAL fold).** §8 Q4
   wording said "FE always sends without `alpha`"; that contradicted
   §B3 hook signature and §7.5 cache-key isomorphism (BE Redis key
   includes alpha). T9 ships alpha=0.05 explicitly through the hook →
   query-key → URL chain so the FE React Query cache slot stays
   isomorphic to the BE Redis slot. No code change — code has been
   correct since T5; only §8 Q4 wording was stale.
7. **T9 — §8 Q1 catalog dropdown grouping deferred (Codex T12 r1
   CRITICAL fold).** §8 Q1 default said "single flat dropdown grouped
   by root via section headers"; T9 ships flat ungrouped because the
   grouping is purely cosmetic (no URL / cache-key / test-contract /
   BE-surface impact). Layered in additively in PR-C hardening or a
   small follow-up PR.

---

## Verification

### ✅ Completed locally

| Layer | Count | Note |
|:---|---:|:---|
| FE vitest | **858/858** pass across 96 files | Was 825 + 29 RED at T7 → 854 GREEN at T9 → 856 at T10 base → 857 at T10 r1 → 858 at T11 (parity test for 27 correlation keys with 3-key invariant allowlist) |
| FE Pact consumer | **26/26** pass | Was 21 baseline → 26 (T8: catalog + populated + insufficient_sample_at_lag + degenerate/low_count_suppressed reason discrimination + 422 insufficient_sample) |
| FE production build | green | `corepack pnpm run build` (tsc -b + vite); root tsconfig has `files=[]`, so `tsc --noEmit` is a no-op — see `feedback_real_build_check` |
| OpenAPI snapshot | empty diff | T6 regen confirmed BE-unchanged (190,076 bytes / 35 paths byte-identical to committed snapshot); CI drift guard `4 passed in 2.64s` |

Run locally:

```bash
cd apps/frontend
corepack pnpm vitest run --reporter=basic    # expect 858 pass
corepack pnpm run test:contract              # expect 26 pass
corepack pnpm run build                      # expect green

cd ../../services/api
uv run pytest tests/contract/test_openapi_snapshot.py -q   # expect 4 pass
```

### 🟡 Pending (CI / user-side)

- **T13 — BE-side Pact verifier hook validation.** Add 5
  `_ensure_correlation_*_fixture` state handlers to
  `services/api/src/api/routers/pact_states.py` mapping the 5
  `.given(...)` strings from T8. Local replay should show 5/5 new
  interactions verify; legacy 21 interactions still pass.
- **T14 — Manual smoke (user-side).** Per umbrella §11 + AC #8: log in
  as `analyst@dev.local` → `/dashboard` → click new top-nav `Correlation`
  → page renders populated state with default `reports.total ×
  incidents.total`. Locale toggle KO ↔ EN — every visible string swaps.
  Command-palette path `⌘K → "correlation" / "상관"` lands on the same
  route.
- **CI green on push.** PR will be opened DRAFT first; the 12-check ×
  2-event = 24-success surface (validated end-to-end on PR #35) is
  expected to flip green within ~10 min of push.
- **Final external Codex review (PR-as-diff loop).** Per
  `feedback_codex_iteration` 3-6 rounds typical; LOWs at the PASS gate
  are fold-or-skip.

### Acceptance criteria (per plan §7)

| # | Criterion | Status |
|:---:|:---|:---:|
| 1 | `pnpm run build` exits 0 | ✅ |
| 2 | All FE tests green (no xfail / xskip introduced) | ✅ |
| 3 | `pageClass.test.tsx` green; manifest contains exactly 10 entries | ✅ |
| 4 | 6 vitest component-test groups (4-state, URL, toggle, banner, chips, shared-cache) | ✅ |
| 5 | Pact consumer regenerates with +5 interactions | ✅ |
| 6 | Provider verify passes all interactions | 🟡 (T13) |
| 7 | OpenAPI snapshot diff at PR head is empty | ✅ |
| 8 | Manual smoke through dev triad | 🟡 (T14) |
| 9 | Manual i18n smoke | 🟡 (T14) |
| 10 | Branch CI green on all 12 checks × 2 events | 🟡 (after push) |
| 11 | Plan doc + PR body present | ✅ (this PR) |
| 12 | Final Codex review reports no unresolved CRIT/HIGH | 🟡 (PR-as-diff) |

---

## What's NOT in this PR (deferred to next slice-3 hardening PR — umbrella §11 PR-C)

- **Lighthouse target wiring + 6-target loop expansion.**
- **Playwright E2E coverage of UAT 1-5.**
- **Performance smoke against populated DB asserting NFR-1 (p95 ≤ 500
  ms).**
- **Power-user any-two-series API** (umbrella §10.1 — out of slice-3
  scope entirely).
- **Quarterly / yearly granularity** (§10.2 — out of scope).
- **F-2 / F-4 / F-5 downstream consumers** (§10.3-10.5 — out of scope).
- **Cross-pair correction** (§10.6 — out of scope).

---

## Reviewer test plan

```bash
# Stack
docker compose up -d db cache keycloak otel-collector
set -a && source envs/api.env.local && set +a
(cd services/api && uv run --all-extras python ../../scripts/_run_api_dev.py)
(cd apps/frontend && npx --yes pnpm@9 dev)

# Test suites
(cd apps/frontend && corepack pnpm vitest run)            # expect 858 pass
(cd apps/frontend && corepack pnpm run test:contract)     # expect 26 pass
(cd apps/frontend && corepack pnpm run build)             # expect green
(cd services/api && uv run pytest tests/contract/test_openapi_snapshot.py -q)
```

Browser at `http://localhost:5173`:

1. Log in as `analyst@dev.local` / `test1234` → land on `/dashboard`.
2. New `Correlation` entry appears in the top-nav (5th item after
   Dashboard / Reports / Incidents / Actors); nav scrolls horizontally
   on narrow viewports rather than pushing trigger + user menu off-
   screen.
3. Click `Correlation` → land on `/analytics/correlation`.
4. Caveat banner renders with "Correlation ≠ causation" / "상관관계 ≠
   인과관계" copy. Dismiss → banner disappears within the tab.
5. Open a new tab → caveat banner reappears (sessionStorage per-tab
   scope).
6. X/Y disclosure dropdowns surface the catalog list. Pick `reports.total`
   for X and `incidents.total` for Y → page transitions from
   empty-state to populated-state with a 49-point lag chart, both
   Pearson + Spearman series visible.
7. Toggle `Spearman` ↔ `Pearson` → active-method opacity highlight
   switches; chart caption stays put; **DevTools Network: zero new
   requests** (toggle is purely visual; method is NOT in the cache key).
8. URL hydrates with `?x=...&y=...&method=...`; reload → state survives;
   back/forward → state survives.
9. Locale toggle KO ↔ EN — every visible string swaps. The 6 warning-
   chip codes each have distinct ko + en copy.
10. `⌘K` → type `correlation` / `상관` → `Go to Correlation` /
    `상관관계로 이동` selectable; pressing it lands on the same
    route.

API surface checks (via dev triad):

```bash
curl -b "session=<cookie>" 'http://localhost:8000/api/v1/analytics/correlation/series' | jq .
curl -b "session=<cookie>" 'http://localhost:8000/api/v1/analytics/correlation?x=reports.total&y=incidents.total' | jq '.lag_grid | length'  # expect 49
curl -i -b "session=<cookie>" 'http://localhost:8000/api/v1/analytics/correlation?x=reports.total&y=reports.total'  # expect 422 identical_series
```

---

## Decision log highlights

- **Page-local URL state route gate over encoder rewrite** (Codex T10
  r1 CRITICAL). Encoder rewrite would have changed
  `urlStateSearchString` semantics for every consumer of
  `useFilterUrlSync` (45 existing tests); route-scope is a 4-line
  addition + 1 dep array entry that leaves the encoder unchanged.
  Future page-local URL state owners extend the `isPageLocalUrlState`
  predicate. New memory anchor: `pattern_page_local_url_state_route_gate`.
- **Custom disclosure dropdowns over native `<select>`** for X/Y
  pickers. Native `<select>` doesn't expose per-option testids
  deterministically under happy-dom + user-event v14; the test contract
  pins `correlation-filter-y-option-incidents.lazarus`-style testids,
  which only a button + listbox-of-button-options layout satisfies.
- **`<input type="text">` over `<input type="date">`** for date inputs.
  happy-dom's `type="date"` typing is unreliable; plain text input
  accepts char-by-char `user.type('2024-01-01')` verbatim.
- **`DraftDateInput` with ISO regex commit gate.** Without the gate,
  typing `2024-01-01` against the real API would issue 9 partial
  fetches (`?date_from=2`, `?date_from=20`, ...) all rejected as 422 +
  cache pollution. Local draft state + commit-only-on-`/^\d{4}-\d{2}-\d{2}$/`
  match keeps URL + cache key stable.
- **49-cell explicit raw array for Pact length-pin** (Codex T8 r1
  CRITICAL). `eachLike` generates `min: 1`, `arrayContaining` doesn't
  pin total length; both miss the umbrella §4.4 + BE pydantic + FE Zod
  49-cell lock at provider-verify time. Fold = `Array.from({length:49}, ...)`.
  New memory anchor: `pattern_pact_explicit_array_for_length_pin`.
- **Negative-branch regression test for the URL-strip CRITICAL.** The
  T10 fix's regression test asserts `correlation-empty` is NOT in
  document, rather than `correlation-populated` IS. Robust because the
  test doesn't seed the catalog with the deep-link's series IDs.
- **TDD ordering:** Step 1 inventory → Step 6 OpenAPI snapshot → Step 8
  Pact (per `pattern_tdd_10step_inventory_shape_before_contract`).
- **i18n parity invariant allowlist** (per
  `pattern_cross_locale_parity_with_invariant_allowlist`): scientific
  method names (`Pearson`, `Spearman`) + ISO 8601 format token
  (`YYYY-MM-DD`) intentionally identical across locales. Remaining 24
  correlation keys must differ ko vs en — copy-paste guard.

---

## Pre-merge checklist

- [x] FE 858 / contract 26 / FE build green
- [x] OpenAPI snapshot diff empty (T6)
- [x] Pact contract JSON regenerated (21 → 26 interactions; +5 per umbrella §7.6) and committed
- [x] EN + KO i18n strings present for the 5 components (27 keys; parity check guards drift)
- [x] No `data-testid` removals; no OpenAPI line removals; URL_STATE_KEYS unchanged
- [x] Page-class manifest 9 → 10 (added `/analytics/correlation`); bi-directional drift test green
- [x] Plan doc (`docs/plans/correlation-fe.md`) + PR body draft (`docs/plans/correlation-fe-body.md`) committed; both rename to `pr{N}-*` post-opening
- [ ] T13 — BE-side Pact verifier state handlers added; local replay 5/5 new interactions verify
- [ ] T14 — Manual smoke through dev triad (user-side)
- [ ] Push DRAFT; CI 12 × 2 = 24 green
- [ ] Final external Codex PR-as-diff review reports no unresolved CRIT/HIGH (per `feedback_codex_iteration`)

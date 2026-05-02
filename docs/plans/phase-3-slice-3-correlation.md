# Phase 3 Slice 3 — D-1 Correlation Analysis (Umbrella Planning Spec)

**Document type:** Umbrella planning spec for Phase 3 Slice 3.
**Scope lock:** D-1 (Pearson + Spearman + lag cross-correlation, p-값 표시) only. F-2 attribution graph / F-4 geopolitical / F-5 CVE weaponization are mapped as **future slots**, not as implementation requirements of this slice.
**PR number:** None reserved. Implementation PRs follow the existing `docs/plans/pr{N}-*.md` convention (e.g. `pr{N}-correlation-be.md`, `pr{N}-correlation-fe.md`, `pr{N}-correlation-hardening.md`); numbers are assigned at PR open time.
**Status:** 🔒 **Locked 2026-05-03** — Codex r6 returned 0 CRITICAL + 0 HIGH (convergence trace in §15). Implementation PRs (`pr{N}-correlation-be.md`, `pr{N}-correlation-fe.md`, `pr{N}-correlation-hardening.md`) follow.
**Design-doc anchors:** §6.2 D-1 (analysis features), §14 Phase 3 W2 (roadmap), §2.5 (relational schema), §7.6 (API endpoints — D-1 slot empty), §7.7 (performance), §13 (UX click-through — D-1 trigger empty).
**Plan-doc convention precedent:** PR #23 (`pr23-lazarus-parity.md`).
**Reviewer corrections folded in (2026-05-02):** zero-fill `no_data` vs `zero_count` distinction, both Pearson + Spearman returned (no auto-pick), BH-FDR with explicit per-(pair, method) family scope, lag direction single-sentence lock, N≥30 minimum, API response carries both `interpretation_caveat` and `methodology_note`, BE primitives ↔ FE viz PRs separated.

---

## 0. Lock summary (pinned invariants)

Five lines that survive implementation debate:

1. **Scope = D-1 only.** Implementation locks the statistical primitive (Pearson / Spearman / lag CCF) plus a single read-only API endpoint plus a single FE chart surface. F-2 / F-4 / F-5 are mapped as downstream consumers in §10 with **no requirements** locked here.
2. **Both Pearson and Spearman are returned for every (X, Y, lag) cell.** No auto-pick; the API is method-deterministic. The UI surfaces both with a method toggle.
3. **Lag convention — verbatim API and UI text:** *"Positive lag = X leads Y by k months."* Wherever the lag value k is shown to a human or a machine consumer, this exact sentence is the contract.
4. **Minimum sample size = N≥30.** Below threshold the API responds 422 `insufficient_sample`; the UI renders the empty state with the same code surfaced as a typed reason. No silent return of statistically meaningless r/p values.
5. **Correlation ≠ causation is a structural API contract, not just UI dressing.** Every correlation response carries `interpretation.caveat` (text) and `interpretation.methodology_url` (link). The FE banner reinforces but does not replace.

---

## 1. Goal

Land the design doc §6.2 D-1 statistical primitive — *Pearson + Spearman + lag cross-correlation(±24개월) with p-value display* — as a read-only analytics endpoint and a single-page FE visualization, scoped tightly enough that downstream Phase 3 work (F-2 / F-4 / F-5) can plug into the same statistical policy and DTO without renegotiation.

**Non-goals:**

- F-2 attribution probability graph (separate slice; design doc §6.1 F-2)
- F-4 geopolitical event correlation (separate slice; depends on `geopolitical_events` ingestion pipeline which does not exist yet — table exists per migration 0001 but is empty)
- F-5 CVE weaponization graph (separate slice; depends on a normalized CVE↔report co-occurrence aggregator that is also not built)
- F-6 forecasting (Phase 4 territory per design doc §14)
- Full power-user "any-two-series" API (locked as future slot in §10.1)
- Materialized views (design doc §7.7 W2 carry — D-1 stays on live aggregation; MV optimization is post-merge)
- Streaming / real-time correlation
- Causal inference (Granger causality, transfer entropy, etc.) — explicitly out

**Mapping to design doc v2.0:**

| Design doc anchor | This slice |
|:---|:---|
| §6.2 D-1 (Pearson + Spearman + lag CCF + p-values) | **Implemented** |
| §14 Phase 3 W2 ("D-1 상관분석(lag) + F-4 지정학 상관") | D-1 only; F-4 deferred |
| §7.6 API endpoint slot | **Filled** with `/api/v1/analytics/correlation` (new) |
| §13 UI trigger | **Filled** with new analytics → correlation page (route locked in §8) |
| §2.5 schema | Statistical source data reuses existing fact tables (`reports`, `incidents`, `incident_motivations`, `incident_sectors`, `incident_countries`, `report_codenames`, `report_techniques`); D-1 adds **one** small `correlation_coverage` table (migration `0009`) solely to back the `no_data` API contract — see §4.2 + §11 PR A |
| §7.7 performance | p95 ≤ 500ms target carried; caching per §7 below |
| §6.2 §6.1 F-2 / F-4 / F-5 | Future slot mapping in §10, no requirements |

---

## 2. Data inventory — what's correlatable

### 2.1 Existing series (already aggregated by other endpoints)

These are the time series the existing analytics surface already exposes (or trivially derives). Any of these is a candidate variable for correlation.

| Series ID | Source endpoint | Bucket | Filter context |
|:---|:---|:---|:---|
| `reports_total` | `/api/v1/analytics/trend` | monthly | `date_from / date_to / group_id[]` |
| `reports_by_group[g]` | derivable from `/trend` with `group_id=[g]` | monthly | per group |
| `reports_by_technique[t]` | derivable from `/attack_matrix` (currently aggregated, not time-sliced) | **needs aggregator extension** | per technique |
| `incidents_total` | `/api/v1/dashboard/summary.incidents_by_year` | yearly (existing); monthly extension required | global |
| `incidents_by_motivation[m]` | `/api/v1/analytics/incidents_trend?group_by=motivation` | monthly | per motivation |
| `incidents_by_sector[s]` | `/api/v1/analytics/incidents_trend?group_by=sector` | monthly | per sector |
| `incidents_by_country[c]` | derivable from `incidents` × `incident_countries` | **not exposed yet** | per country |

### 2.2 Curated series catalog (D-1 lock)

D-1 ships with a **curated catalog of named series** the API recognizes by ID. A request specifies series by ID; the BE resolves them to fact-table queries. This avoids exposing arbitrary SQL and bounds the optimization surface.

Locked catalog for the first slice:

```
reports.total
reports.by_group.<group_id>           # one entry per group_id from /actors
incidents.total
incidents.by_motivation.<key>         # keys = enum from /incidents_trend
incidents.by_sector.<key>             # keys = enum from /incidents_trend
incidents.by_country.<iso2>           # one entry per ISO-2 from /geo
```

The series catalog is itself an API resource — `GET /api/v1/analytics/correlation/series` returns the available IDs with display labels. This makes the FE a thin client and lets future slices extend the catalog without breaking the FE.

### 2.3 Out-of-catalog (future slot)

- `reports.by_motivation.<key>` — requires `#motivation` tag normalization at the report level (currently only on incidents). Future slot mapped in §10.
- `reports.by_country` — no schema path from `reports` to `country`. Future slot.
- `incidents.by_attribution_confidence` — `incidents.attribution_confidence` exists but is sparse. Future slot.
- `geopolitical.events.<type>` — depends on F-4 ingestion. Future slot.

---

## 3. Functional requirements

**FR-1 — Two-series correlation, single lag.** Given two series IDs from the catalog and a date window, return Pearson r and Spearman ρ with their two-tailed p-values at lag = 0.

**FR-2 — Two-series correlation, lag scan.** For the same pair, return the full CCF over lag k ∈ [-24, +24] months, for both Pearson and Spearman, with p-values BH-FDR-corrected within the (pair, method) family of 49 lag tests.

**FR-3 — Catalog discovery.** `GET /correlation/series` returns the available series IDs, display labels, and bucket granularity. The FE relies on this for the dropdowns.

**FR-4 — 4-state render.** Loading / error / empty / populated. Empty includes `insufficient_sample` (N < 30 in the resolved window) as a typed reason rendered with explicit copy.

**FR-5 — URL state.** Selected (X, Y) pair, date window, and method toggle (Pearson/Spearman primary view) serialize to URL query string. Bookmarkable and shareable per design doc §8.1 convention.

**FR-6 — i18n.** All user-facing strings (chart labels, tooltips, axis legends, caveats) carry both `ko` and `en` resources. Korean is the primary copy.

**FR-7 — Interpretation contract (correlation ≠ causation).** Every successful correlation response carries `interpretation.caveat` and `interpretation.methodology_url`. The FE renders the caveat as a sticky banner adjacent to the chart and links the methodology URL.

### Non-functional requirements

**NFR-1 — Performance.** p95 ≤ 500ms for FR-1 and FR-2 over the existing data volume (228 actors / 3458 reports / 229 incidents). Cache TTL 5 min (matches `/dashboard/summary`).

**NFR-2 — RBAC.** 5-role read (`analyst / researcher / policy / soc / admin`) — same as the existing analytics surface.

**NFR-3 — Rate limit.** 60/min per user, per-decorated-route bucket — same as `/attack_matrix` etc.

**NFR-4 — Determinism.** Same input → same output, including p-values to 6 decimal places. No floating-point nondeterminism allowed (use stable computation paths in scipy/statsmodels).

**NFR-5 — Pact contract.** Endpoint added to `contracts/openapi/` snapshot and `contracts/pacts/`. Both happy and `insufficient_sample` 422 cases pinned.

### UAT acceptance criteria

The slice ships green when:

1. A user logs in as `analyst`, opens the correlation page, picks `reports.total` × `incidents.total` over the full date range, sees both Pearson and Spearman values rendered with p-values, sees the caveat banner, and the lag chart renders with [-24, +24] x-axis.
2. The same flow with a window of < 30 monthly buckets shows the empty state with copy "표본이 부족합니다 (최소 30개월 필요)" / "Insufficient sample (minimum 30 months required)" — not a 500, not a silent zero.
3. A direct GET to `/api/v1/analytics/correlation?x=reports.total&y=incidents.total&date_from=2018-01-01&date_to=2026-04-30` returns both methods' (r, p) at lag 0 plus the full lag scan, with `interpretation.caveat` and `interpretation.methodology_url` present.
4. URL state survives reload — opening the bookmarked URL re-renders the same chart.
5. Korean / English locale toggle swaps all chart labels including the caveat banner.
6. p95 over 50 sequential requests against the populated DB ≤ 500 ms.

---

## 4. Data linkage criteria

This section locks the statistical-primitive plumbing — how raw rows become time series, how missing months are handled, and how lag is signed.

### 4.1 Time series construction

**Series rooting:**
- Reports-rooted series → `reports.published` is the bucket date.
- Incidents-rooted series → `incidents.reported` is the bucket date.

**Cross-rooting is forbidden in a single pair only when methodology requires it.** A user can correlate `reports.by_group.<g>` (reports-rooted) with `incidents.by_motivation.<m>` (incidents-rooted) — the bucket date column differs, but as long as both produce the same monthly bucket grid `YYYY-MM`, alignment is well-defined. The API does not block this; the methodology page documents the caveat.

**Bucket format:** `YYYY-MM` string, identical to `/trend` and `/incidents_trend`. No new bucket grammar.

**Bucket fill in the BE:** unlike `/trend` (which omits zero-count months), the correlation aggregator **must produce a dense grid** over the requested window — a missing month becomes a typed cell, not a dropped row. See §4.2.

### 4.2 Missing-value handling — `no_data` vs `zero_count` (reviewer correction #2)

A monthly cell is one of three states, never silently coerced:

| Cell state | Meaning | Numeric value used in correlation | Counted toward N? |
|:---|:---|:---|:---|
| `zero_count` | The query window covers a normalized-data period AND no rows match the predicate. Genuine zero. | `0` | **Yes** |
| `no_data` | Pre-bootstrap period, post-cutoff period, vendor outage window, or any period the data-quality ledger flags as un-normalized. | NaN — **dropped pairwise** before correlation computation | **No** (effective N is reduced) |
| `valid` | A normalized-data period with at least one matching row. | Actual count | Yes |

**How `no_data` is determined:**

The current data-quality ledger (`dq_events` per migration 0005) does not carry per-series coverage windows. For the first slice, `no_data` periods are sourced from a small **coverage table** keyed on `(series_root, bucket)`. The first cut populates this table with hardcoded coverage windows derived from bootstrap dates and the earliest `published` per source — see §11 PR breakdown for the migration. **Locked:** `no_data` is a first-class API concept from day one; the table source can evolve, but the contract cannot.

**Why this matters:** zero-fill is mathematically convenient but lies when the data is structurally absent. Reviewer correction explicitly forbids zero-filling un-normalized periods; cells with zero rows in such periods are `no_data`, not `zero_count`. Correlation then runs pairwise — when either series has `no_data` at month t, that month is excluded from the (X, Y) computation.

**Effective N** is the count of months where both series are `valid` or `zero_count`. If effective N < 30 → 422 `insufficient_sample` (FR-4 + NFR-1 link).

### 4.3 Time bucket granularity

**Locked default:** `monthly` bucket (`YYYY-MM`). Matches existing `/trend` and `/incidents_trend` convention.

**Future slot (NOT in D-1 lock):** `quarterly` and `yearly` granularity. Reviewer mandate is D-1 only; granularity expansion is a future slice that touches both BE and FE shape. Listed in §10.2.

### 4.4 Lag window and direction

**Locked range:** k ∈ [-24, +24] months, integer step. 49 lag values per scan.

**Locked direction (reviewer correction #4 — single sentence, used verbatim in API description and UI tooltip):**

> **Positive lag = X leads Y by k months.**

This means: at lag k = +3, the response cell `r_pearson` is the correlation between `X[t-3]` and `Y[t]`. At k = -3, it is `X[t+3]` vs `Y[t]` (X lags Y).

**API field name:** `lag` (integer, can be negative).
**UI axis label:** the verbatim locked sentence — `Positive lag = X leads Y by k months.` — appears as the lag-axis tooltip / caption in both ko and en. No paraphrase, no truncation.
**Single-source-of-truth:** the verbatim sentence lives at i18n key `correlation.lag.direction_sentence`. API description, OpenAPI summary, methodology page H2, and UI axis caption all resolve from this key. R-13 covers drift detection.

**Reasoning (informational, not part of lock) — calendar-aware lag pairing:**

We pair on the **dense `YYYY-MM` grid** with `no_data`-typed sentinel cells preserved through the lag shift, then drop pairs where either side is `no_data` AFTER shifting. This is critical: collapsing the grid to valid-only rows BEFORE shifting would conflate "k valid observations" with "k calendar months" whenever an internal `no_data` period exists (per §4.2 — vendor outage, pre-bootstrap, etc.).

Concretely, on a dense calendar array of length `N`:
- For `k ≥ 0`: pair `X[t]` with `Y[t+k]` for `t = 0..N-k-1`.
- For `k < 0`: pair `X[t]` with `Y[t+k]` for `t = -k..N-1` (equivalent to pairing `X[-k..N]` with `Y[0..N+k]`).
- After shifting, drop pairs where either `X[t]` or `Y[t+k]` is `no_data`.
- `effective_n_at_lag` = count of remaining shifted pairs (NOT `N_total - |k|`).

This labels lag k as "X leads Y by k calendar months" for positive k (the locked sentence), and statsmodels' `tsa.stattools.ccf(y, x)` convention matches when the input arrays are pre-aligned to the same calendar grid.

---

## 5. Statistical policy

### 5.1 Minimum sample size (reviewer correction #5)

**Locked:** N ≥ 30 effective months for both Pearson and Spearman. Below threshold the API returns 422 with the FastAPI-uniform `detail[]` envelope (matches `/incidents_trend` / `/attack_matrix` convention — see §7.3 for the full shape):

```http
HTTP/1.1 422 Unprocessable Entity
Content-Type: application/json

{
  "detail": [
    {
      "loc": ["body", "correlation"],
      "msg": "Minimum 30 valid months required after no_data exclusion; got <N>",
      "type": "value_error.insufficient_sample",
      "ctx": { "effective_n": <N>, "minimum_n": 30 }
    }
  ]
}
```

The FE error parser switches on `detail[0].type` to drive the empty-state copy.

**Why N ≥ 30, not N ≥ 10 (Spearman convention):** at N = 10, even Spearman has wide CIs and BH-FDR over 49 lag tests virtually always rejects. Conservative N ≥ 30 keeps the response interpretable and rules out the temptation to display r-values from nearly-empty series.

**Lag-scan effective-N adjustment (CRITICAL — calendar-aware, NOT `N_total - |k|`):**

`effective_n_at_lag` is computed per §4.4 calendar-aware pairing — pair on the dense `YYYY-MM` grid first, drop `no_data` shifted-pairs second. Because internal `no_data` periods are allowed (vendor outages, pre-bootstrap, etc.), the simple subtraction `N_total - |k|` would over-count: a `no_data` month at index `t` invalidates both the pair `(X[t], Y[t+k])` and the pair `(X[t-k], Y[t])`, so it removes up to 2 cells per lag (not 1).

Formal definition: for a dense calendar array of length `N` with cell types `valid` / `zero_count` / `no_data`,
```
effective_n_at_lag(k) = count over t in [max(0,-k), min(N, N-k)) of
                        (cell_type(X, t) ∈ {valid, zero_count}
                         AND cell_type(Y, t+k) ∈ {valid, zero_count})
```

**Locked:** the per-lag cell is computed only if `effective_n_at_lag(k) ≥ 30`; otherwise the cell carries the typed shape with metric fields nullified and `reason = "insufficient_sample_at_lag"` (see §5.2 for the exact null shape).

### 5.2 Pearson vs Spearman — both returned (reviewer correction #2)

**Locked:** every cell carries both methods' `r` and `p`. No auto-pick.

**Locked per-method shape — single shape for ALL lag values, ALL methods, populated and null variants alike** (HIGH r1 fix — Pact `eachLike` requires homogeneous shape):

```jsonc
// Populated cell (effective_n_at_lag >= 30 AND finite r/p):
{
  "lag": 0,
  "pearson":  { "r": 0.412, "p_raw": 0.00021, "p_adjusted": 0.00514, "significant": true,  "effective_n_at_lag": 84, "reason": null },
  "spearman": { "r": 0.398, "p_raw": 0.00031, "p_adjusted": 0.00759, "significant": true,  "effective_n_at_lag": 84, "reason": null }
}
// Insufficient-sample cell (effective_n_at_lag < 30):
{
  "lag": 24,
  "pearson":  { "r": null,  "p_raw": null,    "p_adjusted": null,    "significant": false, "effective_n_at_lag": 28, "reason": "insufficient_sample_at_lag" },
  "spearman": { "r": null,  "p_raw": null,    "p_adjusted": null,    "significant": false, "effective_n_at_lag": 28, "reason": "insufficient_sample_at_lag" }
}
// Degenerate cell (zero variance OR non-finite r/p after compute — see §7.4):
{
  "lag": 12,
  "pearson":  { "r": null,  "p_raw": null,    "p_adjusted": null,    "significant": false, "effective_n_at_lag": 60, "reason": "degenerate" },
  "spearman": { "r": null,  "p_raw": null,    "p_adjusted": null,    "significant": false, "effective_n_at_lag": 60, "reason": "degenerate" }
}
// Low-count suppressed cell (R-16 disclosure mitigation — raw monthly counts on one or both shifted-pair series fall below the suppression threshold):
{
  "lag": 6,
  "pearson":  { "r": null,  "p_raw": null,    "p_adjusted": null,    "significant": false, "effective_n_at_lag": 78, "reason": "low_count_suppressed" },
  "spearman": { "r": null,  "p_raw": null,    "p_adjusted": null,    "significant": false, "effective_n_at_lag": 78, "reason": "low_count_suppressed" }
}
```

**Six fields per method block, always present, every cell:** `r` (float \| null), `p_raw` (float \| null), `p_adjusted` (float \| null), `significant` (bool, defaults `false` when null), `effective_n_at_lag` (int, always present), `reason` (enum-string \| null).

**Locked `reason` enum (4 values):** `null` (populated), `"insufficient_sample_at_lag"` (effective_n_at_lag < 30, §5.1), `"degenerate"` (zero-variance or non-finite scipy output, §7.4 + R-12), `"low_count_suppressed"` (R-16 disclosure mitigation triggered for the shifted-pair window).

When `reason` is non-null, `r` / `p_raw` / `p_adjusted` MUST be null and `significant` MUST be `false`. Pact uses `eachLike` over this shape with `reason: null` as the canary literal for the populated case; the three non-null reasons are pinned via additional Pact interactions in §7.6.

The FE provides a method toggle for primary highlight; both values render in the tooltip.

**Methodology-note copy locks the disclaimer:**
- Pearson assumes linear relationship and approximate normality of residuals; sensitive to outliers.
- Spearman is rank-based; robust to monotonic non-linear and outliers.
- Disagreement between the two is a signal of non-linearity or outlier influence — methodology page explains.

### 5.3 Multiple comparison correction (reviewer correction #3)

**Locked correction:** Benjamini-Hochberg FDR (BH).

**Locked family scope:** **per-(pair, method) over finite `p_raw` values in the fixed 49-lag scan.** For a single (X, Y) pair and a single method (Pearson or Spearman), BH-FDR is applied across the lag p-values that survived `_safe_*` (i.e. cells with `reason == null`). Cells with `reason ∈ {insufficient_sample_at_lag, degenerate, low_count_suppressed}` are **excluded from the family entirely** — their `p_raw` is null, they do not enter the BH ranking, and their `p_adjusted` stays null. Pearson and Spearman are corrected independently (not pooled), so the effective family size `m` is per-method:

```
m_pearson  = count of lag cells where cell.pearson.reason  is null
m_spearman = count of lag cells where cell.spearman.reason is null
0 ≤ m_method ≤ 49
```

Concretely: a (pair, method) with 10 `insufficient_sample_at_lag` + 5 `degenerate` cells has `m_method = 49 - 15 = 34`, and BH ranks the 34 finite p-values; the other 15 cells keep `p_adjusted: null` and `significant: false`. This is the contract §7.4 pipeline implements.

**Edge case:** if `m_method == 0` for a given method (every lag came back non-null reason), no BH is applied for that method; the response carries the cells as-is. The endpoint still returns 200 — only the missing-grid level (effective_n < 30 at k=0) escalates to 422. The typed `reason` per cell + the §6.2 triggers (low_count_suppressed_cells, non_stationary_suspected, sparse_window, identity_or_containment_suspected) explain WHY there are no significant correlations; no synthetic "all-null" warning is added because §6.2 vocabulary is closed and trigger-anchored.

**Why per-(pair, method):**

- The user's analytical question on the lag chart is "where in the lag range is this pair significantly correlated?" — that's a within-(pair, method) family question.
- Pooling Pearson and Spearman p-values into one family would correct correlated p-values (the two methods are highly correlated for the same pair), inflating the correction unnecessarily.
- Cross-pair correction is **not** D-1's responsibility — the pair selection is user-driven (UI dropdown), not exhaustive grid search. If a future slice needs all-pairs heatmap with cross-pair correction, that's a separate decision (§10.4 Lock candidate).

**API response carries both raw and adjusted p-values** in every cell: `p_raw` (uncorrected) and `p_adjusted` (BH within the pair's lag scan for that method). This lets the FE show either, and lets a power user verify the correction.

**Significance flag:** `significant: bool` in each cell, computed against `p_adjusted < alpha`. `alpha` is a query parameter with default `0.05` (per LC-2 default = exposed). The resolved `alpha` value MUST appear in the response top-level (see §6.1) so that any consumer — FE chart, API caller, Pact test, cache key consumer — has a single deterministic significance rule and never has to assume a hardcoded threshold.

### 5.4 What we explicitly do not compute

- Granger causality / vector autoregression — out of D-1 scope.
- Transfer entropy, mutual information — out.
- Pre-whitening / ARIMA residuals — out for slice 1; methodology page flags spurious-correlation risk for non-stationary series. Listed as Risk in §13.
- Confidence intervals on r — out for slice 1; only p-values are returned. Lock candidate for future.
- Bootstrap CIs for r — out.

---

## 6. Interpretation contract (reviewer correction #6)

`correlation ≠ causation` is structural.

### 6.1 API response — required fields on every 200 response

```jsonc
{
  "x": "reports.total",
  "y": "incidents.total",
  "date_from": "2018-01-01",
  "date_to": "2026-04-30",
  "alpha": 0.05,                            // resolved significance threshold per §5.3
  "effective_n": 84,
  "lag_grid": [/* 49 cells, each with pearson/spearman blocks per §5.2 */],
  "interpretation": {
    "caveat": "...",                          // i18n key in BE; resolved string in response
    "methodology_url": "/docs/correlation-methodology",
    "warnings": []                             // array of typed warnings (see 6.2)
  }
}
```

### 6.2 `interpretation.warnings` — typed warning vocabulary

Each warning is `{ code: string, message: string, severity: "info"|"warn" }`. Locked vocabulary for slice 1:

| Code | Trigger | Severity |
|:---|:---|:---|
| `non_stationary_suspected` | One or both series fail an ADF stationarity test at α=0.05 | `warn` |
| `outlier_influence` | Pearson and Spearman differ by >0.2 in absolute r at lag 0 | `info` |
| `sparse_window` | effective_n is between 30 and 36 (just above threshold) | `info` |
| `cross_rooted_pair` | One series is reports-rooted, the other incidents-rooted | `info` |
| `identity_or_containment_suspected` | One series accounts for ≥95% of the other's monthly counts over the resolved window (e.g. `reports.total` vs `reports.by_group.<g>` when `<g>` is the only group present); R-15 risk | `warn` |
| `low_count_suppressed_cells` | One or more lag cells were suppressed because raw monthly counts on one or both series fell below the disclosure-suppression threshold; R-16 mitigation | `info` |

The FE renders warnings as inline chips beneath the chart. They do not block the response; they shape interpretation.

### 6.3 FE banner copy (i18n keys)

```yaml
ko:
  correlation.caveat.title: "상관관계는 인과관계가 아닙니다"
  correlation.caveat.body: |
    이 차트는 두 시계열의 통계적 동조 정도만 보여줍니다.
    인과 추론을 위해서는 별도의 분석이 필요하며, 시계열의 비정상성·자기상관·외부 요인 등으로
    인해 spurious 상관이 나타날 수 있습니다. 방법론 문서를 참고하세요.
  correlation.methodology.link: "방법론"
en:
  correlation.caveat.title: "Correlation does not imply causation"
  correlation.caveat.body: |
    This chart shows statistical co-movement of two time series only.
    Causal inference requires separate analysis. Spurious correlations can arise from
    non-stationarity, autocorrelation, and unobserved confounders. See methodology.
  correlation.methodology.link: "Methodology"
```

The methodology page itself is a separate static asset — initial version is a single markdown page committed under `docs/methodology/correlation.md` and rendered by the existing FE doc surface. **PR ordering:** the methodology page ships in PR A (BE primitives) so the URL is live before the FE banner links to it.

---

## 7. API surface

### 7.1 Endpoints

```
GET /api/v1/analytics/correlation/series
GET /api/v1/analytics/correlation
```

### 7.2 `GET /correlation/series` — catalog

**Auth:** session cookie, 5-role read.
**Rate limit:** 60/min/user.

**Response 200:**
```jsonc
{
  "series": [
    { "id": "reports.total", "label_ko": "전체 보고서", "label_en": "All reports", "root": "reports.published", "bucket": "monthly" },
    { "id": "incidents.total", "label_ko": "전체 사건", "label_en": "All incidents", "root": "incidents.reported", "bucket": "monthly" },
    { "id": "reports.by_group.42", "label_ko": "Lazarus 보고서", "label_en": "Lazarus reports", "root": "reports.published", "bucket": "monthly" },
    /* ... */
  ]
}
```

### 7.3 `GET /correlation` — primary endpoint

**Query params:**

| Param | Type | Required | Default | Notes |
|:---|:---|:---:|:---|:---|
| `x` | string (series ID) | ✅ | — | Must exist in catalog |
| `y` | string (series ID) | ✅ | — | Must exist in catalog (and ≠ `x`; identical IDs → 422 `identical_series` per R-15) |
| `date_from` | ISO date | — | DB min | |
| `date_to` | ISO date | — | DB max | |
| `alpha` | float (0 < α < 1) | — | 0.05 | Significance threshold — resolved value echoed in `response.alpha` per §6.1. BH-FDR family scope is unchanged (per (pair, method) over the **fixed** 49 lag tests) |

**`lag_max` is intentionally NOT a query parameter.** D-1 always returns the full `[-24, +24]` lag scan = 49 cells per method (§4.4 + §5.3). Variable lag windows would mutate the BH-FDR family size and break the locked statistical contract. Variable-window scans are deferred to a future slice (see Lock candidate update in §12).

**Response 200 happy** (lag_grid cells follow the locked per-method shape from §5.2):
```jsonc
{
  "x": "reports.total",
  "y": "incidents.total",
  "date_from": "2018-01-01",
  "date_to": "2026-04-30",
  "alpha": 0.05,
  "effective_n": 84,
  "lag_grid": [
    {
      "lag": -24,
      "pearson":  { "r": 0.04, "p_raw": 0.78, "p_adjusted": 0.92, "significant": false, "effective_n_at_lag": 60, "reason": null },
      "spearman": { "r": 0.03, "p_raw": 0.80, "p_adjusted": 0.94, "significant": false, "effective_n_at_lag": 60, "reason": null }
    },
    /* ... 47 more, all with the homogeneous 6-field per-method shape ... */
    {
      "lag": 24,
      "pearson":  { "r": null, "p_raw": null, "p_adjusted": null, "significant": false, "effective_n_at_lag": 28, "reason": "insufficient_sample_at_lag" },
      "spearman": { "r": null, "p_raw": null, "p_adjusted": null, "significant": false, "effective_n_at_lag": 28, "reason": "insufficient_sample_at_lag" }
    }
  ],
  "interpretation": {
    "caveat": "Correlation does not imply causation. ...",
    "methodology_url": "/docs/methodology/correlation",
    "warnings": [
      { "code": "non_stationary_suspected", "message": "...", "severity": "warn" }
    ]
  }
}
```

**Response 422 — insufficient sample** (uniform with FastAPI `detail[]` convention, per existing `/incidents_trend` and `/attack_matrix` 422s; HIGH r1 fix to LC-10):
```jsonc
{
  "detail": [
    {
      "loc": ["body", "correlation"],
      "msg": "Minimum 30 valid months required after no_data exclusion; got 18",
      "type": "value_error.insufficient_sample",
      "ctx": {
        "effective_n": 18,
        "minimum_n": 30
      }
    }
  ]
}
```

**Response 422 — identical series** (R-15):
```jsonc
{
  "detail": [
    {
      "loc": ["query", "y"],
      "msg": "x and y must be different series IDs",
      "type": "value_error.identical_series",
      "ctx": { "x": "reports.total", "y": "reports.total" }
    }
  ]
}
```

**Response 422 — series not in catalog:**
```jsonc
{
  "detail": [{ "loc": ["query", "x"], "msg": "series id 'foo.bar' not in catalog", "type": "value_error" }]
}
```

The FE error parser switches on `detail[0].type` (`value_error.insufficient_sample`, `value_error.identical_series`, plain `value_error` for catalog/date validation) to drive the empty-state copy. Single uniform parser path — no domain-specific envelope branch.

**Response 401 / 403 / 429:** identical envelope to `/attack_matrix` etc.

### 7.4 Computation pipeline (CRITICAL r1 fix — dense-grid calendar-aware lag pairing)

```
router (analytics_correlation.py)
  ↓ resolves x / y → fact-table query specs
  ↓ rejects x == y → 422 identical_series (R-15)
read.correlation_aggregator.compute_correlation()
  ↓ build dense monthly calendar grid [m0, m0+1mo, ..., mN-1] over [date_from, date_to]
  ↓ for each series independently:
  ↓   query monthly counts on root date column (reports.published OR incidents.reported)
  ↓   join with correlation_coverage → cell_type ∈ {valid, zero_count, no_data}
  ↓   produce dense array with sentinel for no_data; NEVER collapse the grid
  ↓ k=0 effective_n = count of t where X[t] AND Y[t] are both ∈ {valid, zero_count}
  ↓ if effective_n < 30 → raise InsufficientSample(effective_n, minimum_n=30)
  ↓ for k in -24..+24:
  ↓   compute calendar-aware shifted pairs per §4.4 (NOT N_total - |k|):
  ↓     pair (X[t], Y[t+k]) for t in valid range; drop where either side is no_data
  ↓     effective_n_at_lag = count of remaining shifted pairs
  ↓   build cell using locked 6-field per-method shape (§5.2):
  ↓     if effective_n_at_lag < 30:
  ↓       cell.pearson  = null-shape with reason="insufficient_sample_at_lag"
  ↓       cell.spearman = null-shape with reason="insufficient_sample_at_lag"
  ↓       continue
  ↓     R-16 disclosure suppression (per §13 R-16, applied BEFORE statistic compute):
  ↓       if min_raw_count(X_shifted) < 5 OR min_raw_count(Y_shifted) < 5:
  ↓         cell.pearson  = null-shape with reason="low_count_suppressed"
  ↓         cell.spearman = null-shape with reason="low_count_suppressed"
  ↓         continue
  ↓     pre-compute checks (HIGH r1 fix — degenerate handling, NOT try/except):
  ↓       if var(X_shifted) == 0 OR var(Y_shifted) == 0:
  ↓         cell.* = null-shape with reason="degenerate"; continue
  ↓     r_p, p_p = scipy.stats.pearsonr(X_shifted, Y_shifted)
  ↓     r_s, p_s = scipy.stats.spearmanr(X_shifted, Y_shifted)  # tuple unpack on .correlation/.pvalue
  ↓     post-compute finite check (HIGH r1 fix):
  ↓       for each (r, p) pair, if not (math.isfinite(r) and math.isfinite(p)):
  ↓         that method's block = null-shape with reason="degenerate"
  ↓     fill cell.pearson / cell.spearman with the populated 6-field shape
  ↓ apply BH-FDR within (pair, method) family of cells with finite p_raw, separately per method:
  ↓   m_method = count of cells where cell.<method>.reason is null     (per §5.3 — populated cells)
  ↓   if m_method == 0: skip BH for this method entirely; per-cell `reason` values carry the
  ↓     explanation, and §6.2 warnings are emitted only when their own triggers fire (no synthetic fallback)
  ↓   else: BH-rank the m_method finite p_raw values, set p_adjusted on those (populated) cells only
  ↓   cells with reason != null (any of insufficient_sample_at_lag / degenerate / low_count_suppressed)
  ↓     keep p_adjusted=null and significant=false (excluded from BH family entirely)
  ↓   significant on populated cells = (p_adjusted < alpha)
  ↓ AFTER lag loop — derive warnings from cell results, strictly per §6.2 vocabulary triggers:
  ↓   if ANY cell.<method>.reason == "low_count_suppressed":
  ↓     warnings.append({code: "low_count_suppressed_cells", severity: "info"})  (R-16)
  ↓   if abs(cell_at_k0.pearson.r - cell_at_k0.spearman.r) > 0.2 (when both finite):
  ↓     warnings.append({code: "outlier_influence", severity: "info"})
  ↓   if x_root != y_root:
  ↓     warnings.append({code: "cross_rooted_pair", severity: "info"})
  ↓   if 30 <= effective_n < 36:
  ↓     warnings.append({code: "sparse_window", severity: "info"})
  ↓   ADF stationarity test on each series → "non_stationary_suspected" if either fails at α=0.05
  ↓   identity/containment check → "identity_or_containment_suspected" per R-15
  ↓
  ↓ Note: when m_method == 0 (every cell non-null reason for that method), the §6.2 triggers
  ↓ above naturally surface the cause — low_count_suppressed_cells (R-16), non_stationary_suspected
  ↓ (ADF), sparse_window (borderline N), or the per-cell `reason` field itself. NO synthetic
  ↓ "all-null" warning is emitted, because §6.2 vocabulary is closed and its triggers are
  ↓ semantically anchored. The chart with all p_adjusted=null IS the honest signal "nothing
  ↓ significant"; the typed `reason` per cell explains why.
  ↓ compute warnings (ADF on each series; |Δr| outlier at lag 0; sparse_window; cross_rooted; identity_or_containment per R-15)
  ↓ assemble dict matching CorrelationResponse Pydantic with strict required-field validation
```

**Notes:**
- `scipy.stats.pearsonr` and `spearmanr` can return NaN with a RuntimeWarning rather than raising on zero-variance / all-tied input. Pre-check variance + post-check `math.isfinite` is the safe contract; do NOT rely on `try/except`.
- `scipy.stats.spearmanr` returns a result object with `.correlation` and `.pvalue` (since SciPy 1.9+). Aggregator pins to `scipy>=1.11` per §11 PR A.
- BH-FDR family scope: per-(pair, method) over the populated cells (reason==null). Cells with `reason ∈ {insufficient_sample_at_lag, degenerate, low_count_suppressed}` (all three non-null reasons in the locked enum) are excluded from the family entirely (their `p_adjusted` stays null and `significant=false`).
- Warnings are derived from result cells AFTER the lag loop (§6.2 vocabulary). Notably `low_count_suppressed_cells` is auto-emitted whenever any cell has `reason == "low_count_suppressed"`, ensuring R-16 disclosure surface is never quiet.

### 7.5 Caching (NFR-1 supporting)

Redis cache key: `correlation:v1:{x}:{y}:{date_from}:{date_to}:{alpha}` (no `lag_max` — `[-24, +24]` is fixed per §4.4). TTL 5 minutes. Invalidation on next bootstrap / ingest run is **not** wired in slice 1 — staleness tolerance is 5 min by design (matches `/dashboard/summary`).

### 7.6 Pact contract (NFR-5)

Adds five Pact interactions (per locked per-method shape from §5.2 — all `eachLike` cells share the homogeneous 6-field shape):

1. `correlation_series happy` — catalog list with ≥ 1 series.
2. `correlation happy populated` — populated lag_grid (49 cells), both methods, all `reason: null`, with one warning.
3. `correlation happy with insufficient_sample_at_lag cells` — populated grid where extreme-lag cells carry `reason: "insufficient_sample_at_lag"` (R-12 + §5.1).
4. `correlation happy with degenerate + low_count_suppressed cells` — pins both `reason: "degenerate"` (zero-variance synthetic) and `reason: "low_count_suppressed"` (R-16 mitigation). Demonstrates the full 4-value `reason` enum in one interaction.
5. `correlation insufficient_sample 422` — `detail[]` envelope with `type: "value_error.insufficient_sample"` and `ctx.effective_n`.

OpenAPI snapshot grows by ~7KB (was 5KB; the 4-value `reason` enum + 2 additional interactions add coverage but the per-cell shape stays homogeneous so growth is bounded).

---

## 8. UI surface

### 8.1 Route

`GET /analytics/correlation` (FE route). Reachable from:

- The existing analytics nav (new entry "Correlation / 상관분석")
- A new entry in the command palette (`⌘K → "correlation"`)

### 8.2 Layout

```
┌────────────────────────────────────────────────────────────────┐
│ ← Analytics ▸ Correlation                          🌐 ko / en  │
├────────────────────────────────────────────────────────────────┤
│ ⚠ Correlation does not imply causation. [methodology →]       │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  X: [ reports.total ▾ ]   Y: [ incidents.total ▾ ]            │
│  Date: [2018-01-01] — [2026-04-30]                             │
│  Method primary: ( ) Pearson  ( ) Spearman          (toggle)   │
│                                                                │
├────────────────────────────────────────────────────────────────┤
│ At lag 0:                                                      │
│   Pearson r = 0.412, p (BH-adj) = 0.005   ★ significant       │
│   Spearman ρ = 0.398, p (BH-adj) = 0.008  ★ significant       │
│                                                                │
│   Lag scan caption (verbatim from §4.4 lock):                 │
│   Positive lag = X leads Y by k months.                       │
│   ┌──────────────────────────────────────────────┐             │
│   │           [ recharts LineChart, 480x240 ]    │             │
│   │   r values × lag, with 95% reference band    │             │
│   │   tooltip: cell detail (r, p_raw, p_adj, n)  │             │
│   └──────────────────────────────────────────────┘             │
│                                                                │
│   Warnings:                                                    │
│   [chip] non-stationary suspected                              │
│   [chip] outlier influence (Δ|r| = 0.21)                       │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 8.3 Components

- `CorrelationFilters` (X, Y, date, method toggle)
- `CorrelationCaveatBanner` (sticky, dismiss-once-per-session)
- `CorrelationLagChart` (recharts LineChart, 480×240 fixed dim per `TrendChart` precedent)
- `CorrelationWarningChips`

### 8.4 4-state render (FR-4)

Per `TrendChart.tsx` precedent:
- `loading` → skeleton with `data-testid="correlation-chart-loading"`
- `error` → inline error card + retry button
- `empty` → typed-reason empty card. Three reasons:
  - `insufficient_sample` — "표본이 부족합니다 (최소 30개월 필요, 현재 N=18)"
  - `series_not_found` — "선택한 시계열을 찾을 수 없습니다"
  - generic — "데이터를 불러올 수 없습니다"
- `populated` → full chart layout

### 8.5 URL state (FR-5)

```
URL_STATE_KEYS additions: x, y, date_from, date_to, method
e.g. /analytics/correlation?x=reports.total&y=incidents.total&date_from=2018-01-01&date_to=2026-04-30&method=pearson
```

Existing 5-tuple `URL_STATE_KEYS` (per memory `feedback_phase_ordering` + PR #23 plan) gets a new namespace under `analytics.correlation.*` — additive, no rename.

### 8.6 i18n (FR-6)

New translation keys under `correlation.*`. Both ko and en. The methodology page is bilingual.

### 8.7 Hooks

- `useCorrelationSeries()` — fetches catalog, cached forever per session
- `useCorrelation(x, y, dateFrom, dateTo)` — react-query, 5-min stale time

---

## 9. Performance budget

NFR-1 says p95 ≤ 500ms. Headroom analysis:

- Catalog query: O(M) where M = total series count (≈ 20 in the locked catalog). Trivial.
- Series fetch: 2 × `SELECT bucket, COUNT(*) FROM ...` — both indexed by `published` / `reported`. With current data volume (3458 reports, 229 incidents), both queries are < 50ms warm.
- Lag scan: 49 lags × 2 methods × Python compute. With N=84 monthly buckets, scipy.pearsonr is sub-millisecond per call → ~100ms total.
- BH-FDR: O(L log L) sorting per family — sub-millisecond.
- ADF stationarity test: statsmodels.tsa.stattools.adfuller, ~10-30ms per series → 60ms for both.

**Total budget:** ~150-250ms warm. Headroom is comfortable. Cold-start (cache miss) one-shot runs that risks p95 — Redis cache absorbs subsequent hits.

**Materialized views** (design doc §7.7) — **deferred**. D-1's per-month aggregates are simple enough that MV optimization is post-merge. If p95 drifts above 500ms with future ingestion volume, MV is the lever.

---

## 10. Future slot mapping (NOT implementation requirements)

This section maps how F-2 / F-4 / F-5 / power-user use cases plug into D-1's primitives. **Listed as informational only.** No requirements locked here.

### 10.1 Power-user "any-two-series" API

A future slice could relax the catalog constraint and accept arbitrary series-defining query params (e.g. `x.root=reports&x.filter.tag=APT37&x.bucket=monthly`). D-1's curated catalog is the safer first step; the aggregator architecture can absorb arbitrary series resolvers without contract change.

### 10.2 Quarterly / yearly granularity

`bucket` query param accepting `monthly|quarterly|yearly`. The aggregator uses the same `_month_expr`-style portable bucket function adapted per granularity. Lag window adapts (`±8 quarters` or `±2 years`). FE chart x-axis adapts.

### 10.3 F-2 attribution probability graph (design doc §6.1 F-2)

F-2's "edge weights = report count × confidence" is itself a Pearson-like signal. F-2 can call D-1 internally for edge-validation: "for each (codename, group) edge, is the time-series correlation between codename mentions and group attributions significant?" — D-1's primitive answers this. F-2's UI is a graph viz, not a chart, but the underlying numbers come from the same aggregator.

### 10.4 F-4 geopolitical event correlation (design doc §6.1 F-4)

F-4's "UN sanctions ±30 days → report/incident surge" is a windowed event-study, not a continuous time-series correlation. **F-4 needs a different statistical primitive** (event-aligned permutation test or Poisson regression with intervention term). D-1's CCF is one of several signals F-4 could surface alongside; not a substitute. F-4 also depends on `geopolitical_events` ingestion, which is its own work.

### 10.5 F-5 CVE weaponization graph (design doc §6.1 F-5)

F-5's "CVE × DPRK report co-occurrence" is a categorical co-occurrence graph, not time-series correlation. D-1 plays no direct role; F-5 has its own aggregator. (D-1 could supply a "CVE mention rate × incident count" auxiliary chart, but that's a UI choice, not a dependency.)

### 10.6 Cross-pair correction

If a future slice introduces an all-pairs heatmap (M² pairs displayed simultaneously), cross-pair BH-FDR correction is a Lock candidate. D-1's per-(pair, method) family scope deliberately punts this.

---

## 11. PR decomposition

Locked split: **3 PRs**, BE primitives separated from FE viz per reviewer correction.

### PR A — D-1 BE primitives + methodology page

**Branch:** `feat/p3.s3-correlation-be`
**Scope:**
- New deps: `scipy>=1.11`, `statsmodels>=0.14`. Pinned in `services/api/pyproject.toml`. Worker untouched.
- New module: `services/api/src/api/read/correlation_aggregator.py`
  - `compute_correlation_series_catalog(session) -> dict`
  - `compute_correlation(session, x, y, date_from, date_to, alpha) -> dict`  *(no `lag_max` per §7.3 lock)*
  - `_resolve_series(series_id) -> SeriesResolver` — pluggable per future slot
  - `_build_dense_calendar_grid(...)` — produces `[(bucket, count, cell_type)]` keyed on calendar months; preserves `no_data` cells through to lag pairing (§7.4 pipeline)
  - `_lag_pair_calendar_aware(x_grid, y_grid, k)` — calendar-aware shifted pair builder per §4.4 + §5.1 (NOT pre-collapse)
  - `_lag_scan(x_grid, y_grid) -> list[CellDict]` — fixed `[-24, +24]` scan; emits the locked 6-field per-method shape with explicit `reason` for null cells
  - `_safe_pearsonr(x, y) -> (r, p, reason)` — pre-checks variance, calls scipy, post-checks `math.isfinite`; returns `(None, None, "degenerate")` on failure
  - `_safe_spearmanr(x, y) -> (r, p, reason)` — same contract for Spearman
  - `_apply_bh_fdr(p_values_with_indices, alpha) -> dict[index → p_adjusted]` — operates only on finite p-values; null cells excluded from family
  - `_compute_warnings(x_grid, y_grid, x_root, y_root, results)` — derives all §6.2 warning codes from the lag-grid results: ADF on each series → `non_stationary_suspected`; |Δr| at k=0 between Pearson and Spearman → `outlier_influence`; effective_n in [30, 36) → `sparse_window`; `x_root != y_root` → `cross_rooted_pair`; ≥95% containment over the resolved window → `identity_or_containment_suspected` (R-15); ANY cell with `reason == "low_count_suppressed"` in `results` → `low_count_suppressed_cells` (R-16, ensures the suppression surface is never silent)
- New router: `services/api/src/api/routers/analytics_correlation.py`
  - 422 `identical_series` guard (`x == y` → before any DB hit)
  - 422 `insufficient_sample` translation from aggregator exception → uniform `detail[]` envelope per §7.3
- New DTOs: `CorrelationSeriesItem`, `CorrelationCatalogResponse`, `CorrelationCellMethodBlock` (6 required fields, all metric fields nullable, `reason` nullable), `CorrelationLagCell`, `CorrelationInterpretation`, `CorrelationWarning`, `CorrelationResponse`. **No `InsufficientSampleResponse` DTO** — the 422 follows FastAPI's standard `detail[]` envelope (§7.3 r1 fix).
- New migration: `0009_correlation_coverage.py` — `correlation_coverage(series_root TEXT, bucket TEXT, status TEXT CHECK status IN ('valid','no_data'))` + seed data for known pre-bootstrap windows. Lookup is keyed on `(series_root, bucket)` for O(log N) probe.
- Methodology page: `docs/methodology/correlation.md` (ko/en bilingual). Includes the verbatim lag-direction sentence at §H2 + BH-FDR family-scope explanation + non-stationarity caveat.
- OpenAPI snapshot regen + Pact contract additions (5 interactions per §7.6)
- Tests (PR A):
  - **Unit / aggregator math:** synthetic series with known r/p (e.g., perfect linear → r=1.0, p≈0; flat → degenerate; lagged-by-3 → peak at k=+3 with X-leads-Y direction); calendar-aware lag pairing (synthetic series with internal `no_data` gap proves `effective_n_at_lag` ≠ `N_total - |k|`); BH-FDR family scope (per-method independence); lag direction sentence presence in `correlation_aggregator.compute_correlation.__doc__` AND in `analytics_correlation` router description string.
  - **Unit / DTO negative tests** (MEDIUM r1 fix + r2 family-size lock): `CorrelationResponse.model_validate` rejects payloads missing `lag_grid`, missing `interpretation.caveat`, missing `interpretation.methodology_url`, missing `alpha`; `CorrelationCellMethodBlock.model_validate` rejects payloads missing `effective_n_at_lag`; populated cells with `reason=null` must have all of `r`/`p_raw`/`p_adjusted` non-null AND finite; null-shape cells with non-null `reason` must have all metric fields null; `reason` enum is one of `{null, "insufficient_sample_at_lag", "degenerate", "low_count_suppressed"}` — any other string is rejected. No defaults on required fields.
  - **Unit / BH-FDR family-size regression (r2 fix)**: synthetic 49-cell scan with 10 `insufficient_sample_at_lag` + 5 `degenerate` cells must produce `p_adjusted` on exactly 34 cells per method (m_method=34); the other 15 cells must keep `p_adjusted: null`. Edge case: synthetic scan with `m_method == 0` (every cell non-null reason) returns 200 with no BH applied; the test asserts that no synthetic "all-null" warning is emitted — only the warnings whose §6.2 triggers actually fire (e.g. `low_count_suppressed_cells` if all reasons are `low_count_suppressed`; `non_stationary_suspected` only if ADF says so; otherwise the cells stand on their own typed `reason`).
  - **Unit / R-16 disclosure suppression**: synthetic series where `min_raw_count` per shifted-pair window is < 5 → those lag cells carry `reason: "low_count_suppressed"`. `interpretation.warnings` includes `low_count_suppressed_cells: info`.
  - **Unit / safe primitives:** `_safe_pearsonr` / `_safe_spearmanr` regression — zero-variance input returns `reason="degenerate"`; SciPy NaN-with-warning path returns `reason="degenerate"`; sufficient input returns finite tuple.
  - **Integration:** full pipeline against fixture DB; `identical_series` 422; populated 200; `insufficient_sample` 422 with `ctx.effective_n` < 30.
  - **Pact:** 5 interactions per §7.6 — (1) `correlation_series happy` catalog, (2) `correlation happy populated`, (3) `correlation happy with insufficient_sample_at_lag cells`, (4) `correlation happy with degenerate + low_count_suppressed cells`, (5) `correlation insufficient_sample 422`. Homogeneous 6-field per-method shape pinned via `eachLike` with literal canaries for each non-null `reason` value.
  - **Determinism:** 6-decimal-place stability across runs.
  - **Methodology page:** asserts the verbatim lag sentence is present at the i18n key `correlation.lag.direction_sentence` AND appears in the rendered methodology page H2 (R-13).
- Plan doc: `docs/plans/pr{N}-correlation-be.md`

**Estimated size:** medium-large (≈ 30-40 files, ≈ 1500 LoC excluding generated OpenAPI).

### PR B — D-1 FE viz

**Branch:** `feat/p3.s3-correlation-fe` (rebased onto PR A after merge)
**Scope:**
- New route: `apps/frontend/src/features/analytics/correlation/`
  - `CorrelationPage.tsx`
  - `CorrelationFilters.tsx`
  - `CorrelationCaveatBanner.tsx`
  - `CorrelationLagChart.tsx`
  - `CorrelationWarningChips.tsx`
  - hooks: `useCorrelationSeries.ts`, `useCorrelation.ts`
- URL state additions
- i18n entries (ko + en) under `correlation.*`
- Pact consumer test
- Vitest component tests (4-state render, URL state, method toggle, banner dismiss)
- Plan doc: `docs/plans/pr{N}-correlation-fe.md`

**Estimated size:** medium (≈ 20 files, ≈ 800 LoC).

### PR C — D-1 hardening + UAT

**Branch:** `chore/p3.s3-correlation-hardening`
**Scope:**
- Lighthouse target added (`/analytics/correlation` → 5-target loop becomes 6-target)
- E2E spec under `apps/frontend/e2e/` covering UAT acceptance criteria 1–5
- Performance smoke test against populated DB asserting NFR-1 (p95 ≤ 500ms over 50 sequential requests)
- Codex iteration cycle (3-6 rounds expected per `feedback_codex_iteration`)
- Plan doc: `docs/plans/pr{N}-correlation-hardening.md`

**Estimated size:** small (≈ 8 files, ≈ 300 LoC).

### Dependency DAG

```
PR A (BE + methodology + migration)
  ↓
PR B (FE — depends on PR A's OpenAPI + Pact + methodology URL)
  ↓
PR C (hardening — runs against merged PR A + PR B)
```

PR B can be opened in draft against PR A pre-merge (stacked-PR pattern per `pattern_rebase_preview_throwaway_worktree`); base flips after PR A merges.

---

## 12. Lock candidates

Items that the spec **proposes a default for** but flags for explicit confirmation before implementation lock. **Not Open questions** — the spec carries a recommended value; this list is the "you might want to override" surface.

| # | Item | Spec default | Alternative | Why this might flip |
|:--|:---|:---|:---|:---|
| LC-1 | Series catalog scope | reports.total / reports.by_group / incidents.total / incidents.by_motivation / by_sector / by_country | Add reports.by_technique up front | Technique time series not exposed yet — adds another aggregator |
| LC-2 | `alpha` query param exposed to caller | Yes, default 0.05 | Hardcoded 0.05, no override | Power user UX vs surface minimization |
| LC-3 | Cross-rooted pair (reports × incidents) handling | Allowed; warning chip only | Block as 422 | Methodology page can absorb caveat |
| LC-4 | Lag chart 95% reference band | Show `±1.96/sqrt(effective_n_at_lag)` per cell | Show only BH-significant flag, no band | Visual clutter vs interpretability |
| LC-5 | Methodology page rendering surface | New `docs/methodology/correlation.md` rendered by existing FE doc surface | Embed inline modal | Doc-page reuse vs context proximity |
| LC-6 | Warnings.cross_rooted_pair severity | `info` | `warn` | UX decision — how loud should this signal be |
| LC-7 | `correlation_coverage` table seed source | Hardcoded windows derived from `min(reports.published)` / `min(incidents.reported)` | Pull from `dq_events` if a coverage signal exists | dq_events doesn't carry coverage today — would need extension |
| LC-8 | Banner dismissal scope | Per-session (sessionStorage) | Per-user-forever (DB-backed) | Compliance/UX preference |
| LC-9 | API caveat string i18n | Returned localized to user's session locale (BE-resolved) | BE returns i18n key; FE resolves | Convention with rest of app — needs spot-check |
| LC-10 | ~~Pact 422 envelope shape~~ | ~~Custom~~ → **resolved 2026-05-03 r1**: locked to FastAPI uniform `detail[]` envelope per §5.1 + §7.3. Custom envelope was inconsistent with `/incidents_trend` and `/attack_matrix` actual shape. No flip available; this row stays for traceability. | — | — |
| LC-11 | Variable lag window (`lag_max` query param) | Removed in r1 — `[-24, +24]` is fixed (§7.3 + §7.4). | Re-introduce as a future slice with restated BH-FDR family size (`2*lag_max+1`) | Caller wants tighter scan for small windows; not D-1's job |

---

## 13. Risk register

| ID | Risk | Likelihood | Impact | Mitigation |
|:---|:---|:---:|:---:|:---|
| R-1 | scipy + statsmodels add ~150-200MB to API container layer; build-time and surface increase | High | Medium | Pin minor versions; audit transitively at PR A; consider slim wheels if size becomes an ops concern |
| R-2 | Non-stationary time series produce spurious high correlations; user misreads | Medium | High | `non_stationary_suspected` warning + methodology page paragraph; ADF test on every request |
| R-3 | BH-FDR validity weakened by p-value correlation across lags (CCF p-values are not independent) | Medium | Medium | Methodology page documents; alternative is BY procedure (Benjamini-Yekutieli) which is more conservative — captured as Lock candidate alternative |
| R-4 | Small effective_n at extreme lags inflates noise; the per-lag `insufficient_sample_at_lag` cell could be misread as "no relationship" rather than "no data" | Low | Medium | Cell carries explicit `reason` field; FE chart renders gap with hover tooltip explaining |
| R-5 | Cross-rooted pair correlations (reports × incidents on different date columns) introduce lag-bias if one stream has systematic publication delay | Medium | Medium | `cross_rooted_pair` warning; methodology page; LC-3 considers blocking |
| R-6 | OpenAPI snapshot growth (PR A adds ≈ 5KB; cumulative size still under threshold but watch) | Low | Low | Per memory `openapi_snapshot_size_watch`, monitor; if PR B/C add growth that crosses the readability threshold, path-split is the lever |
| R-7 | Pact contract for the `lag_grid` array is large (49 cells × 2 methods); matchers must be precise to avoid R3-class regex failures (per memory `pattern_pact_literal_pinned_paths`) | Medium | Medium | Use `eachLike` with a single fixed cell shape; pin one literal lag value as the canary; avoid matcher cascade traps |
| R-8 | Methodology page in PR A but FE banner in PR B — short window where the URL 404s | Low | Low | Methodology page ships in PR A, before FE consumes; verified by PR A acceptance test |
| R-9 | Catalog-driven series IDs become unstable if group renames or motivation/sector enums shift | Low | High | Catalog endpoint is the source of truth; FE never hardcodes IDs; ID format documented as opaque |
| R-10 | Coverage table (`correlation_coverage`) is hand-seeded in PR A — drift risk as new sources are ingested | Medium | Medium | Captured as a follow-up TODO in PR A's commit message + memory `followup_todos.md` entry; future slice could derive from `dq_events` (LC-7) |
| R-11 | Computational worst case: catalog grows to M series and a future slice exposes all-pairs heatmap, exploding to M² × 49 lag computations | Low (this slice) | High (future) | D-1 deliberately scopes to single-pair; all-pairs heatmap is a future slice with its own perf decision (LC future) |
| R-12 | Small N at extreme lag + zero variance window (e.g. flat series after warm-up) → scipy.pearsonr / spearmanr returns NaN with a RuntimeWarning rather than raising. `try/except` will NOT catch this. | Medium | Medium | **Pre-call variance check** (`var(X) == 0` or `var(Y) == 0` → cell goes degenerate before scipy is called); **post-call finite check** (`math.isfinite(r)` AND `math.isfinite(p)` → cell goes degenerate if either fails). `_safe_pearsonr` / `_safe_spearmanr` enforce this contract, both unit-tested. See §7.4 pipeline. |
| R-13 | "Positive lag = X leads Y" sentence drifts in translation between API description, OpenAPI spec, methodology page, and UI tooltip | Medium | Medium | Lock the verbatim sentence in the spec (§4.4); tests assert presence in `compute_correlation.__doc__`, router OpenAPI summary, methodology page H2, and UI axis caption text; one source of truth = i18n key `correlation.lag.direction_sentence`. r1 already caught one drift in the original §8.2 chart text — pre-PR-A test coverage is the prevention layer. |
| R-14 | scipy/statsmodels deps pull in transitive packages with CVEs that affect API security surface | Low | Medium | PR A includes `bandit` + `pip-audit` in CI; security-reviewer agent run before merge |
| R-15 | Self-correlation or containment-equivalent series produce tautological `r ≈ 1.0` results (e.g. `reports.total` vs `reports.by_group.<g>` when `<g>` is the only group in the filtered corpus). Users may misread as a discovered relationship. | Medium | Medium | (a) Router-level guard: `x == y` → 422 `identical_series` (§7.3). (b) Aggregator-level warning: when over the resolved date window, `series Y` accounts for ≥ 95% of `series X`'s monthly counts (or vice versa), emit `interpretation.warnings[].code = "identity_or_containment_suspected"` with severity `warn`. Tested explicitly with synthetic single-group corpus. Methodology page documents the containment-equivalence caveat. |
| R-16 | Correlation output over sparse country/sector series may reveal information not exposed by current aggregate endpoints — e.g. `incidents.by_country.<iso2>` is added as a monthly series here while no monthly-by-country endpoint exists today. Even without raw counts, r/p/null/degenerate patterns can leak structure. | Medium | Medium | **Pre-PR-A RBAC/disclosure check** (gate item, MUST resolve before PR A code starts): grep every catalog series ID and confirm its monthly granularity is exposed at the same role level by an existing endpoint OR a planned-in-this-PR endpoint. If not, the catalog is reduced (LC-1 update) OR a minimum-event-count suppression rule is added (`effective_n_at_lag` cells with raw count < 5 are suppressed to `reason: "low_count_suppressed"`). Decision is logged in PR A plan doc §RBAC-disclosure. |

---

## 14. Open questions

(Per reviewer instruction, this section is **deliberately minimal**. Items requiring user/reviewer input but not blocking draft are in §12 Lock candidates. Items genuinely unresolved are below.)

1. **Methodology page content depth** — slice 1 ships a single page. Is a single page sufficient for the analyst persona (§1.4 Aria), or does it need to land alongside a "how to read this chart" Loom-style walkthrough? Recommend single page, accept iteration.

(That's it. All other prior questions resolved into Lock candidates or Risk register entries per reviewer instruction.)

---

## 15. Status log

- 2026-05-02 — Spec draft written. Step 1 read-only research complete. Awaiting Step 3 Codex cross-verify before lock.
- 2026-05-03 — Codex r1 returned 1 CRITICAL + 7 HIGH + 3 MEDIUM + 0 LOW. All findings folded in via narrow-scope spec amendments: (CRITICAL) calendar-aware lag pairing replaces `N_total - |k|`; (HIGH) `_safe_pearsonr` / `_safe_spearmanr` replace `try/except` for degenerate handling; (HIGH) 422 envelope switched to FastAPI `detail[]` uniform shape; (HIGH) homogeneous 6-field per-method cell shape locked; (HIGH) lag-direction sentence unified at i18n key `correlation.lag.direction_sentence`; (HIGH) `lag_max` query param removed (49-cell scan is fixed); (HIGH) `alpha` reconciled — exposed as query param, echoed in response top-level; (HIGH) §1 schema mapping clarified — `correlation_coverage` is the one new table; (MEDIUM) DTO negative tests enumerated; (MEDIUM) R-15 identity/containment + (MEDIUM) R-16 disclosure suppression added.
- 2026-05-03 — Codex r2 returned 0 CRITICAL + 2 HIGH + 0 MEDIUM + 0 LOW. Both HIGH were r1-amendment consistency defects: (HIGH) `low_count_suppressed` reason added in R-16 was not in §5.2's locked enum or the §7.4 pipeline → enum extended to 4 values, R-16 suppression branch placed before statistic compute, Pact interactions extended to pin all 4 reason values; (HIGH) BH-FDR family size was inconsistent (§5.3 said 49, §7.4 said "up-to-49") → §5.3 now locks `m_method = count(reason==null)` per method, §7.4 BH step matches, §11 PR A tests pin the m=34 case.
- 2026-05-03 — Codex r3 returned 0 CRITICAL + 3 HIGH + 0 MEDIUM + 0 LOW. All HIGH were r2-amendment churn: (HIGH) §7.4 BH step had inverted "null-reason" wording + listed only 2 of 3 excluded reasons → re-worded to "reason != null" + listed all 3 (`insufficient_sample_at_lag`, `degenerate`, `low_count_suppressed`); (HIGH) R-16 warning had no emission point in §7.4 pipeline → explicit AFTER-loop warning derivation block added, `low_count_suppressed_cells` triggers when any cell has the matching reason; (HIGH) §11 PR A test list said "4 interactions" while §7.6 had 5 → corrected to 5 with explicit interaction names.
- 2026-05-03 — Codex r4 returned 0 CRITICAL + 1 HIGH + 0 MEDIUM + 0 LOW. The single HIGH was a r3-amendment vocabulary mismatch: (HIGH) §7.4 m_method==0 fallback emitted `non_stationary_suspected` OR `sparse_window` synthetically, but those warnings have semantically anchored triggers in §6.2 (ADF and effective_n respectively) — emitting them outside their triggers would lie. Fix: removed the synthetic fallback. m_method==0 now produces 200 with no BH and the per-cell typed `reason` is the honest signal; §6.2-trigger warnings still fire if their conditions independently apply.
- 2026-05-03 — Codex r5 returned 0 CRITICAL + 1 HIGH + 0 MEDIUM + 0 LOW. Stale parenthetical `(warnings should already flag it)` left over after the r4 removal in §7.4 BH step. Fix: replaced with explicit "per-cell `reason` carries the explanation; §6.2 warnings emitted only when their own triggers fire (no synthetic fallback)" — fully consistent with §5.3 and §11 wording.
- 2026-05-03 — **Codex r6 returned 0 CRITICAL + 0 HIGH + 0 MEDIUM + 0 LOW** — full convergence. Per `feedback_codex_iteration`, the spec is locked. Convergence trace across 6 rounds: r1(1+7+3+0) → r2(0+2+0+0) → r3(0+3+0+0) → r4(0+1+0+0) → r5(0+1+0+0) → r6(0+0+0+0). 18 findings folded total. **Status header flipped from Draft to Locked.** Implementation PRs follow.

---

**End of umbrella spec. Implementation PRs follow.**

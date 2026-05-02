# PR #28 — D-1 Correlation BE primitives + methodology page

**Status:** 🔒 **Plan locked 2026-05-03** — implementation may proceed.
**Parent spec:** `docs/plans/phase-3-slice-3-correlation.md` (locked 2026-05-03 after Codex r1-r6 convergence; treat as the design source of truth for any decision not explicitly named in this plan).
**PR number:** `28` is **provisional** — assigned at PR open time per `feedback_verify_user_signals_via_api`. Filename will be renamed if numbering shifts.
**Base:** `main` @ `6f1a014` (PR #22 merge commit, current `origin/main` HEAD per session memory).
**Branch:** `feat/p3.s3-correlation-be` (separate worktree at `C:\Users\shin1121\Desktop\dprk-cti-correlation-be`; main repo cwd remains on `feat/pr27-visual-redesign-seed`).
**Scope boundary:** services/api + db/migrations + docs/methodology + contracts/{openapi,pacts}. **Zero changes** to services/worker, services/llm-proxy, apps/frontend, infra/keycloak, .github/workflows.
**Stack relationship:** independent of the 5 OPEN PRs. Does NOT stack on PR #23 (which itself is awaiting external review). Lands directly on `main` after spec parent + this plan are locked.

---

## 0. Lock summary (pinned invariants)

Five lines that survive implementation debate:

1. **The umbrella spec is the source of truth.** This plan enumerates what to build; for *why* a behavior is locked the way it is, defer to `docs/plans/phase-3-slice-3-correlation.md` and never re-derive.
2. **No feature-flag gating.** D-1 endpoints land on by default for all 5 read roles. Disclosure-suppression (R-16) and identity-guard (R-15) protect the surface inline; they are not feature flags.
3. **One migration only — `0009_correlation_coverage`.** Schema change is additive: a single coverage table and its seed data. No alter-column on existing tables. Reversible downgrade.
4. **Methodology page ships with this PR, before FE consumes.** `docs/methodology/correlation.md` (ko + en) is committed alongside the BE so the URL `interpretation.methodology_url` returns is live the moment PR A merges (R-8 mitigation).
5. **No FE wiring in this PR.** OpenAPI snapshot + Pact contract land here; FE component code, hooks, route registration, i18n keys for the UI banner — all in PR B (`pr{N}-correlation-fe.md`).

---

## 1. Goal

Land the D-1 statistical primitive (Pearson + Spearman + lag CCF over fixed `[-24, +24]`) as a read-only analytics endpoint that satisfies the umbrella spec's API contract end-to-end. After merge, an authenticated `analyst` role can `GET /api/v1/analytics/correlation?x=reports.total&y=incidents.total` and receive the locked 6-field-per-method 49-cell `lag_grid` plus `interpretation.{caveat,methodology_url,warnings}` plus a live methodology page.

**Non-goals (PR A):**

- FE chart rendering (PR B)
- `/analytics/correlation` route registration in the FE (PR B)
- E2E test suite (PR C)
- Lighthouse target addition (PR C)
- p95 hardening / cache warmup (PR C)
- Any catalog series beyond §2 lock list of this plan
- F-2 / F-4 / F-5 future-slot work
- Rerunning Codex r1-r6 against this plan doc itself; this plan inherits the spec's lock and adds only PR-specific decisions

---

## 2. R-16 disclosure / RBAC pre-check resolution

The umbrella spec requires this gate item to resolve before code starts. Resolution:

**Catalog vs existing exposure matrix:**

| Catalog series | Monthly already exposed? | Same RBAC roles? | Decision |
|:---|:---|:---|:---|
| `reports.total` | ✅ `/api/v1/analytics/trend` monthly buckets | ✅ same 5-role read | catalog OK |
| `reports.by_group.<group_id>` | ✅ `/trend?group_id=<g>` monthly buckets | ✅ same | catalog OK |
| `incidents.total` | ⚠️ only yearly via `/dashboard/summary.incidents_by_year` | ✅ same 5-role read | catalog OK with suppression |
| `incidents.by_motivation.<key>` | ✅ `/incidents_trend?group_by=motivation` monthly | ✅ same | catalog OK |
| `incidents.by_sector.<key>` | ✅ `/incidents_trend?group_by=sector` monthly | ✅ same | catalog OK |
| `incidents.by_country.<iso2>` | ⚠️ only date-window total via `/geo` | ✅ same 5-role read | catalog OK with suppression |

**Disclosure analysis:** the two ⚠️ rows expose monthly granularity that no existing endpoint surfaces. However:

1. The data is already accessible in finer granularity to the same 5 roles via the `/incidents` list endpoint with `date_from / date_to` filters and per-row `reported`, `country_iso2`, etc. — the user can compute monthly-by-country counts manually today by querying the list and bucketing client-side. Correlation does not introduce a new data egress path; it provides an aggregation convenience.
2. The R-16 suppression rule (cells with `min_raw_count < 5` on the shifted-pair window become `reason="low_count_suppressed"`) is the primary mitigation against inferring sparse-bucket information from r/p patterns.
3. RBAC is uniform — no role can see `/incidents` list at finer granularity than another. So the catalog is not a privilege-escalation surface; it is a granularity-inference surface, addressed by suppression.

**Locked:** the full §2 catalog ships in PR A. R-16 suppression is enforced uniformly across ALL series (not just the two ⚠️ rows) so the contract is invariant to which series the user picks. No catalog reduction.

**Threshold rationale:** `min_raw_count < 5` is conservative for monthly buckets at our data volume (3458 reports / 229 incidents over 15 years ≈ 19 reports / 1.3 incidents per month average; 5 is the threshold above which a small DPRK-CTI-relevant signal is unlikely to be unique-attributable to a single incident).

This resolution is the LOCK — no further re-litigation in PR A. If LC-1 (catalog scope) is later flipped to add `reports.by_technique`, the R-16 matrix re-runs at that decision point.

---

## 3. File inventory

### 3.1 New files (sources of additions)

```
db/migrations/versions/
  0009_correlation_coverage.py                              # alembic migration

services/api/src/api/
  read/correlation_aggregator.py                            # statistical primitives + pipeline
  routers/analytics_correlation.py                          # thin router
  schemas/correlation.py                                    # Pydantic DTOs (new module to keep schemas/read.py focused)

services/api/tests/
  unit/test_correlation_aggregator_math.py                  # synthetic series math + lag direction
  unit/test_correlation_aggregator_calendar.py              # dense-grid calendar-aware pairing
  unit/test_correlation_aggregator_safe_primitives.py       # _safe_pearsonr / _safe_spearmanr
  unit/test_correlation_aggregator_bh_fdr.py                # family-size + m=34 + m=0
  unit/test_correlation_aggregator_warnings.py              # 6.2 vocabulary triggers
  unit/test_correlation_aggregator_suppression.py           # R-16 low_count_suppressed
  unit/test_correlation_aggregator_identity.py              # R-15 identical_series + containment
  unit/test_correlation_dto_negative.py                     # Pydantic strict-required-field tests
  integration/test_correlation_e2e.py                       # router → DB fixture → response
  contract/test_pact_correlation_provider.py                # 5 Pact interactions
  data/correlation_fixtures.py                              # synthetic series fixtures

services/api/src/api/
  tables.py                                                 # ADD correlation_coverage_table mirror

contracts/openapi/
  api-snapshot.json                                         # REGEN (additive)

contracts/pacts/
  frontend-api-correlation.json                             # NEW pact file (provider-side fixture)

docs/methodology/
  correlation.md                                            # bilingual ko/en methodology page
```

### 3.2 Modified files (additive only)

```
services/api/pyproject.toml                                 # add scipy, statsmodels, numpy
services/api/uv.lock                                        # uv sync regenerates
services/api/src/api/main.py                                # register analytics_correlation.router
services/api/src/api/tables.py                              # mirror new table (per pitfall_subpackage_parents_offset stale-watch)
```

### 3.3 No-touch zones

```
services/worker/        — untouched
services/llm-proxy/     — untouched
apps/frontend/          — untouched (PR B owns FE)
infra/                  — untouched
.github/workflows/      — untouched (existing pytest + uv lock check picks up the migration + deps)
```

---

## 4. Migration 0009 — `correlation_coverage`

### 4.1 Schema

```python
op.create_table(
    "correlation_coverage",
    sa.Column("series_root", sa.Text(), nullable=False),
    sa.Column("bucket", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint("series_root", "bucket", name="pk_correlation_coverage"),
    sa.CheckConstraint(
        "status IN ('valid', 'no_data')",
        name="correlation_coverage_status_allowed",
    ),
)
op.create_index(
    "ix_correlation_coverage_series_root",
    "correlation_coverage",
    ["series_root"],
    unique=False,
)
```

`series_root` values are exactly the `root` field exposed by the catalog API — initial set: `"reports.published"`, `"incidents.reported"`. `bucket` is `YYYY-MM`.

### 4.2 Seed strategy

Seed at migration time (not via separate seed CLI) so the no_data contract is live the moment the DB upgrades. Two source-derived window sets:

- **`reports.published` no_data** — months strictly before the earliest `reports.published` date (per memory `phase_status` DB span starts 2009-07-08, so months `1900-01` through `2009-06` get `status='no_data'`; everything from `2009-07` onward defaults to `valid`).
- **`incidents.reported` no_data** — months strictly before the earliest `incidents.reported` date.

Implementation: migration runs two `INSERT INTO correlation_coverage SELECT ...` statements that compute the windows from a synthetic `generate_series` of months bounded by `min(reports.published)` / `min(incidents.reported)` (via embedded SQL in the migration). For sqlite test environments the migration uses a fallback hardcoded month-list helper.

Seed total row count: ~110 years × 12 months = ~1320 rows × 2 series_roots = ~2640 rows. Trivial size; one-time insert at migration.

**Internal `no_data` periods (vendor outages, etc.) are NOT seeded** in PR A — they live as a follow-up extension once the DQ ledger evolves to carry coverage signals (LC-7). PR A's seed is the pre-bootstrap-only baseline.

### 4.3 Downgrade

```python
op.drop_index("ix_correlation_coverage_series_root", table_name="correlation_coverage")
op.drop_table("correlation_coverage")
```

Reversible; no data dependency from any other table.

### 4.4 SQLAlchemy Core mirror in `tables.py`

Add `correlation_coverage_table` matching the migration column-for-column. Per `followup_todos` note "SQLAlchemy Table mirror drift — `tables.py` mirrored through 0007 at last update; still hand-maintained" — this PR's mirror is a reminder that drift continues. Not introduced by PR A.

---

## 5. Dependency additions

### 5.1 Versions

```toml
# services/api/pyproject.toml
dependencies = [
  ...
  "scipy>=1.11,<2",
  "statsmodels>=0.14,<0.16",
  "numpy>=1.24,<3",                 # transitive of scipy/statsmodels but pinned for reproducibility
  ...
]
```

Rationale per spec §11 + R-1:
- `scipy>=1.11`: spearmanr returns `SignificanceResult` object (since 1.9); `>=1.11` is the floor where `pearsonr` returns the same dataclass shape consistently. No specific upper-bound concern beyond major-version skew.
- `statsmodels>=0.14`: `tsa.stattools.adfuller` and `ccf` are stable since 0.14. `<0.16` reserves room for one minor bump but caps before any potential 1.0 API break.
- `numpy>=1.24,<3`: required by both. Capping at `<3` per current numpy 2.x compatibility window.

### 5.2 Wheel availability (verified 2026-05-03)

PyPI metadata confirmed:
- `scipy 1.17.x` cp312 wheels for both `win_amd64` and `manylinux2014_x86_64` ✓
- `statsmodels 0.14.x` cp312 wheels for both ✓ (~10 MB compressed)
- `numpy 2.4.x` cp312 wheels for both ✓

R-1 (container size +150-200MB) is real but expected; no wheel-availability blocker.

### 5.3 Security audit gate

Per umbrella spec R-14 mitigation:
- `pip-audit` runs in CI as a new step in `services/api`'s pytest workflow (additive — not a global CI pipeline change).
- `bandit` runs in CI on the new module set (`services/api/src/api/read/correlation_aggregator.py`, `routers/analytics_correlation.py`).
- `security-reviewer` agent invocation is captured as a self-review step in this PR's commit message footnote.

Audit runs are advisory at first (no CI gate failure on findings) — gate flip is post-merge if findings are clean.

---

## 6. Aggregator implementation plan

### 6.1 Module shape

`services/api/src/api/read/correlation_aggregator.py` — public + private API per umbrella spec §11 PR A. Function signatures:

```python
async def compute_correlation_series_catalog(
    session: AsyncSession,
) -> dict[str, list[dict[str, str]]]:
    """Returns {"series": [...]} per spec §7.2."""

async def compute_correlation(
    session: AsyncSession,
    *,
    x: str,
    y: str,
    date_from: date | None,
    date_to: date | None,
    alpha: float,                   # NO lag_max — per spec §7.3
) -> dict[str, object]:
    """Returns CorrelationResponse-shaped dict per spec §7.3."""
```

Private helpers (testable independently):

```python
def _resolve_series(series_id: str, session: AsyncSession) -> SeriesResolver: ...
def _build_dense_calendar_grid(...) -> list[GridCell]: ...
def _lag_pair_calendar_aware(x_grid, y_grid, k: int) -> tuple[list, list, int]: ...
def _safe_pearsonr(x_arr, y_arr) -> tuple[float | None, float | None, str | None]: ...
def _safe_spearmanr(x_arr, y_arr) -> tuple[float | None, float | None, str | None]: ...
def _apply_bh_fdr(p_values: list[float], alpha: float) -> list[float | None]: ...
def _compute_warnings(x_grid, y_grid, x_root, y_root, results) -> list[dict]: ...
def _check_identity_or_containment(x_grid, y_grid) -> bool: ...
```

### 6.2 Variance / suppression / safe-primitive contracts

```python
def _safe_pearsonr(x_arr, y_arr):
    if len(x_arr) < 30:
        return (None, None, "insufficient_sample_at_lag")
    if min(x_arr) < 5 or min(y_arr) < 5:        # R-16
        return (None, None, "low_count_suppressed")
    if statistics.variance(x_arr) == 0 or statistics.variance(y_arr) == 0:
        return (None, None, "degenerate")
    r, p = scipy.stats.pearsonr(x_arr, y_arr)
    if not (math.isfinite(r) and math.isfinite(p)):
        return (None, None, "degenerate")
    return (float(r), float(p), None)
```

(Pseudo-pyhton; actual variance check uses numpy `var(ddof=0) == 0` on the array slice. The check ordering matches §7.4 pipeline: insufficient → suppressed → degenerate → finite check → success.)

### 6.3 Calendar-aware lag pairing (§4.4 + §5.1 of umbrella spec)

```python
def _lag_pair_calendar_aware(x_grid, y_grid, k):
    """Returns (x_arr, y_arr, effective_n_at_lag) for calendar-aligned pairs."""
    n = len(x_grid)
    pairs = []
    if k >= 0:
        t_range = range(0, n - k)
    else:
        t_range = range(-k, n)
    for t in t_range:
        x_cell = x_grid[t]
        y_cell = y_grid[t + k]
        if x_cell.cell_type == "no_data" or y_cell.cell_type == "no_data":
            continue
        pairs.append((x_cell.count, y_cell.count))
    if not pairs:
        return ([], [], 0)
    x_arr, y_arr = zip(*pairs)
    return (list(x_arr), list(y_arr), len(pairs))
```

### 6.4 Determinism contract (NFR-4)

- All math uses doubles via `float()` cast at boundary.
- BH-FDR sort uses stable sort on `(p, original_index)` tiebreaker.
- p-values rounded to 6 decimal places at DTO serialization (NOT at compute) so internal math precision is preserved.

---

## 7. Router implementation plan

`services/api/src/api/routers/analytics_correlation.py` — thin per existing analytics router precedent.

### 7.1 Endpoints

```python
@router.get("/correlation/series", response_model=CorrelationCatalogResponse, ...)
@_limiter.limit("60/minute")
async def correlation_series_endpoint(...): ...

@router.get("/correlation", response_model=CorrelationResponse, ...)
@_limiter.limit("60/minute")
async def correlation_endpoint(...): ...
```

### 7.2 Pre-DB validation

```python
if x == y:
    raise HTTPException(
        status_code=422,
        detail=[{
            "loc": ["query", "y"],
            "msg": "x and y must be different series IDs",
            "type": "value_error.identical_series",
            "ctx": {"x": x, "y": y},
        }],
    )
```

### 7.3 InsufficientSample → 422

Aggregator raises `InsufficientSampleError(effective_n: int, minimum_n: int)`. Router catches and translates per spec §7.3:

```python
except InsufficientSampleError as exc:
    raise HTTPException(
        status_code=422,
        detail=[{
            "loc": ["body", "correlation"],
            "msg": f"Minimum 30 valid months required after no_data exclusion; got {exc.effective_n}",
            "type": "value_error.insufficient_sample",
            "ctx": {"effective_n": exc.effective_n, "minimum_n": exc.minimum_n},
        }],
    ) from exc
```

### 7.4 Caching (§7.5)

Redis key per spec, TTL 5 min. Cache miss path runs aggregator; cache hit returns deserialized payload directly. Cache implementation reuses the existing pattern from `dashboard_aggregator` (verify with `grep -l "redis" services/api/src/api/read/`).

---

## 8. DTO module

`services/api/src/api/schemas/correlation.py` — new, separate from `schemas/read.py` to keep imports tight.

```python
class CorrelationSeriesItem(BaseModel):
    id: str
    label_ko: str
    label_en: str
    root: Literal["reports.published", "incidents.reported"]
    bucket: Literal["monthly"]

    model_config = ConfigDict(extra="forbid", strict=True)

class CorrelationCatalogResponse(BaseModel):
    series: list[CorrelationSeriesItem]

class CorrelationCellMethodBlock(BaseModel):
    r: float | None                       # required, nullable
    p_raw: float | None                   # required, nullable
    p_adjusted: float | None              # required, nullable
    significant: bool                     # required, defaults False when null elsewhere
    effective_n_at_lag: int               # required, never null
    reason: Literal[
        "insufficient_sample_at_lag",
        "degenerate",
        "low_count_suppressed",
    ] | None                              # required, nullable for populated cells

    @model_validator(mode="after")
    def _validate_null_consistency(self) -> CorrelationCellMethodBlock:
        if self.reason is not None:
            if self.r is not None or self.p_raw is not None or self.p_adjusted is not None:
                raise ValueError("non-null reason requires r/p_raw/p_adjusted to be null")
            if self.significant:
                raise ValueError("non-null reason requires significant=False")
        else:
            if self.r is None or self.p_raw is None or self.p_adjusted is None:
                raise ValueError("populated cell (reason=null) requires all of r/p_raw/p_adjusted to be non-null")
        return self

class CorrelationLagCell(BaseModel):
    lag: int                              # required, range -24..+24
    pearson: CorrelationCellMethodBlock
    spearman: CorrelationCellMethodBlock

class CorrelationWarning(BaseModel):
    code: Literal[
        "non_stationary_suspected",
        "outlier_influence",
        "sparse_window",
        "cross_rooted_pair",
        "identity_or_containment_suspected",
        "low_count_suppressed_cells",
    ]
    message: str
    severity: Literal["info", "warn"]

class CorrelationInterpretation(BaseModel):
    caveat: str
    methodology_url: str
    warnings: list[CorrelationWarning]

class CorrelationResponse(BaseModel):
    x: str
    y: str
    date_from: date
    date_to: date
    alpha: float
    effective_n: int
    lag_grid: list[CorrelationLagCell]    # always 49 cells
    interpretation: CorrelationInterpretation

    model_config = ConfigDict(extra="forbid", strict=True)
```

`extra="forbid"` + `strict=True` everywhere keeps the contract from silently absorbing unknown fields. No defaults on required fields.

---

## 9. Test enumeration

### 9.1 Unit tests

| File | Coverage |
|:---|:---|
| `test_correlation_aggregator_math.py` | (a) Perfect linear synthetic Y = 2X + 3 → r=1.0, p<1e-10 at k=0; (b) Lagged synthetic Y[t] = X[t-3] → peak at k=+3; (c) verbatim sentence "Positive lag = X leads Y by k months." appears in `compute_correlation.__doc__` |
| `test_correlation_aggregator_calendar.py` | Dense calendar pairing with internal `no_data` gap proves `effective_n_at_lag` ≠ `N_total - |k|`; covers k=0, k=+5 (gap inside window), k=-12 |
| `test_correlation_aggregator_safe_primitives.py` | `_safe_pearsonr` / `_safe_spearmanr` regression — zero-variance, NaN-with-RuntimeWarning, sufficient input, low_count_suppressed input |
| `test_correlation_aggregator_bh_fdr.py` | (a) m_method=49 happy; (b) m_method=34 (10 insuff + 5 degen) — 34 cells get p_adjusted, 15 stay null; (c) m_method=0 — no BH applied, no synthetic warning, 200 returned |
| `test_correlation_aggregator_warnings.py` | All 6 §6.2 codes each independently testable: ADF fail → non_stationary_suspected; |Δr|>0.2 → outlier_influence; effective_n in [30,36) → sparse_window; reports×incidents → cross_rooted_pair; ≥95% containment → identity_or_containment_suspected; any low_count_suppressed cell → low_count_suppressed_cells |
| `test_correlation_aggregator_suppression.py` | R-16 — synthetic series where shifted-pair `min_raw_count<5` → cell carries `reason="low_count_suppressed"` AND `low_count_suppressed_cells` warning emitted |
| `test_correlation_aggregator_identity.py` | R-15 — `x == y` → router 422 `identical_series`; ≥95% containment → 200 with `identity_or_containment_suspected` warning |
| `test_correlation_dto_negative.py` | `CorrelationResponse.model_validate` rejects missing `lag_grid`, missing `alpha`, missing `interpretation.caveat`, missing `interpretation.methodology_url`, missing `effective_n_at_lag`, populated cell with null `r`, null cell with non-null `r`, unknown `reason` enum value |

### 9.2 Integration test

`test_correlation_e2e.py` — uses the existing fixture-DB pattern (per `services/api/conftest.py`); scenarios:

1. Happy GET `/correlation?x=reports.total&y=incidents.total` over full window → 200 with 49-cell grid + warnings list; assert all 6 §6.2 warning code positions are well-formed (codes that don't apply are simply absent from the array).
2. `x == y` → 422 `identical_series`.
3. Window narrow enough that effective_n < 30 → 422 `insufficient_sample` with `ctx.effective_n` < 30.
4. Authenticated as each of 5 read roles (analyst / researcher / policy / soc / admin) → all 200; non-authenticated → 401.
5. Catalog GET `/correlation/series` → 200 with all 6 catalog entries (matches §2 lock list).

### 9.3 Pact provider verification

`test_pact_correlation_provider.py` — 5 interactions per umbrella spec §7.6:

1. `correlation_series happy`
2. `correlation happy populated`
3. `correlation happy with insufficient_sample_at_lag cells`
4. `correlation happy with degenerate + low_count_suppressed cells`
5. `correlation insufficient_sample 422`

Provider-state handlers in `services/api/src/api/routers/pact_states.py` (extend existing `pact_states.py` per memory `pattern_pact_dependency_override_via_provider_state`).

### 9.4 Determinism test

`test_correlation_aggregator_math.py::test_determinism_6_decimal_stability` — run `compute_correlation` 10 times with identical input; assert all r/p values to 6 decimal places are byte-identical across runs.

### 9.5 Methodology page test

`test_methodology_page_lag_sentence.py` — assert `"Positive lag = X leads Y by k months."` appears verbatim in `docs/methodology/correlation.md` (R-13 prevention).

---

## 10. Methodology page outline

`docs/methodology/correlation.md` — bilingual ko/en, ~150-250 lines:

```
# 상관분석 방법론 / Correlation Analysis Methodology

## 1. 무엇을 계산하는가 / What we compute
   - Pearson r, Spearman ρ at lag 0 + lag scan over [-24, +24]
   - p-values raw + BH-FDR adjusted

## 2. 시간 정렬 / Lag alignment
   - VERBATIM: "Positive lag = X leads Y by k months." (i18n key correlation.lag.direction_sentence)
   - 캘린더 정렬 / Calendar-aware pairing

## 3. 다중 비교 보정 / Multiple comparison correction
   - BH-FDR per (pair, method)
   - 가족 크기 m_method = count(reason==null)

## 4. correlation ≠ causation
   - 핵심 면책 / Core disclaimer
   - 비정상성 / Non-stationarity caveat
   - 자기상관 / Autocorrelation note
   - 외부 변수 / Confounders

## 5. 경고 표시 해석 / Warning code reference
   - 6 codes from §6.2 with detailed semantics

## 6. 무엇을 계산하지 않는가 / What we don't compute
   - Granger causality, transfer entropy, CIs, pre-whitening (per spec §5.4)

## 7. 한계 / Limitations
   - 비정상 시계열 spurious 위험 / Spurious correlation risk on non-stationary series
   - 작은 N에서의 BH 무력화 / BH ineffective at small N
   - 식별/포함 관계 자기 자신 상관 / Identity/containment self-correlation
```

---

## 11. Pact contract details

5 interactions per spec §7.6. File: `contracts/pacts/frontend-api-correlation.json` (fresh provider-side fixture; does NOT extend the existing `frontend-api.json` to keep shape pinning isolated).

Per memory `pattern_pact_literal_pinned_paths` — interactions use literal dates in the `999000` range for fixture stability + ON CONFLICT (id) upsert on BE state handlers. Per `pitfall_pact_js_matchers_on_headers` — Content-Type uses plain string, never regex matchers.

`eachLike` pinned shapes per cell:
- Interaction #2 pins one literal lag=0 cell with `reason: null` as canary
- Interaction #3 pins one literal lag=23 cell with `reason: "insufficient_sample_at_lag"` as canary
- Interaction #4 pins TWO literal lags: lag=12 with `reason: "degenerate"` and lag=6 with `reason: "low_count_suppressed"` (both in one interaction to amortize the family-size synthetic fixture cost)

---

## 12. OpenAPI snapshot delta

Expected growth: ~7KB (per spec §7.6 estimate). Verified post-implementation by `pnpm run snapshot` (or equivalent) before commit.

Per memory `openapi_snapshot_size_watch` — current snapshot was 85KB at PR #11. Post-PR-A estimate: 85KB + 7KB ≈ 92KB. Still under any documented size threshold; if PR B adds non-trivial growth, the path-split lever activates.

---

## 13. Risk register (PR-specific subset)

| ID | Risk (this PR) | Mitigation |
|:---|:---|:---|
| PR-R1 | Migration `0009` seed insertion races with concurrent DB activity | Migration runs in transaction; atomic; no `migrate-while-running` semantics expected (per `followup_todos` "Bootstrap CLI is one-shot" precedent) |
| PR-R2 | `services/api/uv.lock` regen produces unrelated transitive bumps | Inspect `uv lock --diff` before commit; revert any non-related package shifts |
| PR-R3 | Pact verifier expects coverage table seeded; provider state handler must seed if absent | State handler `correlation_coverage_seeded` upserts the baseline before each Pact interaction |
| PR-R4 | scipy/statsmodels Docker layer rebuild slow on CI | Cache pip wheel cache in CI per existing service-api workflow |
| PR-R5 | `_safe_pearsonr` ordering bug — wrong reason emitted for borderline edge case | Unit test enumerates all 4 possible orderings explicitly |

Spec-level risks (R-1 through R-16) inherit from umbrella; PR A does not re-derive.

---

## 14. Open questions

(Deliberately minimal per umbrella spec §14 norm.)

1. **Pact V3 cold-start race risk** — the 5-interaction contract may trigger `pitfall_pact_v3_ci_cold_start_race`. Mitigation if encountered: retry-first per memory; do not modify test or code on a single rerun-pass case.

(That's it. All other concerns are in umbrella spec or §13 above.)

---

## 15. Acceptance criteria

This PR ships green when:

1. `services/api` pytest passes 100% (existing tests + ~9 new test files).
2. `services/api` mypy / ruff clean on new files.
3. Migration `0009` upgrade + downgrade both succeed against fresh sqlite + against the existing dev PG (`docker exec dprk-cti-db-1 psql -U postgres -d dprk_cti`).
4. `pact-python` provider verifier passes 5/5 interactions on the new contract file.
5. OpenAPI snapshot regen produces only the expected ~7KB additive delta (no unrelated diffs).
6. `bandit` + `pip-audit` produce no CRITICAL / HIGH findings on the new code paths.
7. Local dev server (`uv run uvicorn`) starts cleanly, `GET /api/v1/analytics/correlation/series` returns 200 with the locked catalog, `GET /api/v1/analytics/correlation?x=reports.total&y=incidents.total` returns 200 with 49-cell grid + non-empty warnings array.
8. Methodology page renders correctly in browser at `/docs/methodology/correlation` (or whatever path the existing FE doc surface uses; verify before merge).
9. Self-review pass: `code-reviewer` agent + `security-reviewer` agent run, all findings classified per `feedback_self_review_false_positive_triage`.

---

## 16. Self-review and Codex iteration plan

After local green:

1. Run `code-reviewer` agent on all new files.
2. Run `security-reviewer` agent on the new router + DTO + migration.
3. Address local critical / high findings; classify any false positives per `feedback_self_review_false_positive_triage`.
4. Write `.codex-review/prompt-pr28-r1.txt` with narrow scope (statistical correctness, API contract integrity, migration safety, RBAC/disclosure, lag direction sentence presence, BH-FDR family scope).
5. Run Codex via `bash .codex-review/run-codex-review.sh 1` (rename harness for PR-context if cleaner: `run-codex-review-pr28.sh`).
6. Iterate per `feedback_codex_iteration` (3-6 rounds expected).
7. After 0 CRITICAL + 0 HIGH: commit + STOP. Do not push or open PR; user-confirmation gate.

---

## 17. User-confirmation gate

The following actions require explicit user sign-off and are NOT performed by the autonomous loop:

- `git push -u origin feat/p3.s3-correlation-be`
- `gh pr create --base main --title "feat: D-1 correlation BE primitives + methodology page" --body ...`
- Any `gh pr edit`, `gh pr ready`, `gh pr merge` operation

Halt point: after local green + Codex green, summarize what is ready and wait.

---

## 18. Status log

- 2026-05-03 — Plan written. Locked at draft time because it inherits from the locked umbrella spec; no separate Codex review on the plan doc itself (per `feedback_codex_iteration` 3-6-round budget already spent on the spec).

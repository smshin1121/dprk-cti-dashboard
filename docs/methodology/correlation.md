# 상관분석 방법론 / Correlation Analysis Methodology

> Phase 3 Slice 3 D-1 — `GET /api/v1/analytics/correlation` 엔드포인트의 통계 정책을 설명하는 단일 출처 문서.
> Single-source-of-truth methodology for the D-1 correlation endpoint.

---

## 1. 무엇을 계산하는가 / What we compute

두 시계열 X, Y에 대해 다음을 계산합니다 / For two time series X and Y, we compute:

- **Pearson r** — 선형 상관계수, 정규성 가정 / linear correlation, assumes approximate normality
- **Spearman ρ** — 순위 기반 상관, 단조 비선형에 견고 / rank-based, robust to monotonic non-linearity
- **Lag cross-correlation** — `k ∈ [-24, +24]` (49 lag values), 매 lag마다 두 방법 모두 계산 / both methods at every lag
- **p-values** — raw + Benjamini-Hochberg FDR adjusted

응답 데이터는 항상 49개의 lag cell을 포함하며, 각 cell은 Pearson과 Spearman 두 method 블록을 가집니다 (각 6개 필드 고정). The response always carries 49 lag cells; each cell has Pearson and Spearman blocks with 6 fixed fields.

---

## 2. 시간 정렬 — lag 방향 / Lag alignment — direction

### Positive lag = X leads Y by k months.

이 단일 문장은 i18n 키 `correlation.lag.direction_sentence`에 고정되어 있으며, API 설명, OpenAPI 스펙, 본 방법론 문서, FE 차트 caption 모두에서 동일하게 표시됩니다. This exact sentence is locked at i18n key `correlation.lag.direction_sentence` and surfaces identically in API description, OpenAPI spec, this methodology page, and the FE chart caption.

구체적으로 / Concretely:
- `lag k = +3`: `corr(X[t-3], Y[t])` — X가 3개월 먼저 / X leads by 3 months
- `lag k = -3`: `corr(X[t+3], Y[t])` — X가 3개월 늦음 / X lags by 3 months
- `lag k = 0`: 동시점 상관 / contemporaneous

### 캘린더 정렬 / Calendar-aware pairing

내부 `no_data` 기간(부트스트랩 이전, 벤더 outage 등)이 있어도 lag shift는 **dense YYYY-MM 격자에서** 수행됩니다. 즉, 먼저 짝짓기, 그 다음 `no_data` 제외 (반대가 아님). Even when internal `no_data` periods exist, lag shifts run on the **dense YYYY-MM grid** — pair first, drop `no_data` shifted-pairs second (not the reverse).

수식 / Formula:
- For `k ≥ 0`: pair `X[t]` with `Y[t+k]` for `t ∈ [0, N-k)`, drop where either is `no_data`
- For `k < 0`: pair `X[t]` with `Y[t+k]` for `t ∈ [-k, N)`, same drop rule
- `effective_n_at_lag` = 남은 짝의 수 (NOT `N_total - |k|`) / count of remaining pairs

---

## 3. 결측 처리 / Missing-value handling

월별 cell은 다음 세 상태 중 하나입니다 / Each monthly cell is one of three types:

| Cell type | 의미 / Meaning | 상관 계산에 포함? / Included in correlation? |
|:---|:---|:---|
| `valid` | 정규화된 기간의 1+ 행 / 1+ rows in normalized period | ✅ |
| `zero_count` | 정규화된 기간이지만 0건 — 진짜 0 / normalized period, 0 rows — genuine zero | ✅ |
| `no_data` | 부트스트랩 이전, 벤더 outage 등 비정규화 / pre-bootstrap, vendor outage, un-normalized | ❌ (pairwise drop) |

`no_data` 분류는 `correlation_coverage` 테이블이 source입니다. zero-fill은 **수학적으로 편하지만 데이터가 구조적으로 부재할 때는 거짓말**이므로 사용하지 않습니다. The `no_data` classification is sourced from `correlation_coverage`. Zero-fill is **mathematically convenient but lies when data is structurally absent**, so we don't do it.

---

## 4. 다중 비교 보정 / Multiple comparison correction

**Benjamini-Hochberg FDR**, family scope = **per-(pair, method)** over finite p-values in the fixed 49-lag scan.

```
m_pearson  = count of cells where cell.pearson.reason  is null
m_spearman = count of cells where cell.spearman.reason is null
0 ≤ m_method ≤ 49
```

Pearson과 Spearman은 독립적으로 보정됩니다 (한 family로 풀링하지 않음). 두 method의 p-value가 같은 (X, Y) 쌍에서 강하게 상관되어 있어, 풀링하면 보정이 필요 이상으로 보수적이 됩니다. Pearson and Spearman are corrected independently — pooling would over-correct because the two methods' p-values are strongly correlated for the same pair.

`reason ∈ {insufficient_sample_at_lag, degenerate, low_count_suppressed}` cells는 BH family에서 완전히 제외됩니다. Cells with non-null `reason` are excluded from the BH family entirely.

### 한계 / Caveat — BH-FDR validity assumption

BH-FDR은 p-value들이 독립이거나 PRDS (positive regression dependent on subsets) 조건을 만족할 때 엄밀하게 유효합니다. CCF의 인접 lag p-value들은 자기상관으로 인해 상관되어 있으므로, 엄격한 BH 가정은 약하게 위반됩니다. 더 보수적인 대안은 Benjamini-Yekutieli 절차이지만, 본 슬라이스에서는 BH의 실용성을 우선시하고 본 caveat을 통해 사용자에게 알립니다. BH-FDR is strictly valid under independence or PRDS; CCF p-values across adjacent lags are correlated via autocorrelation, so the assumption is mildly violated. BY is a more conservative alternative, deferred to a future slice.

---

## 5. correlation ≠ causation

이 차트는 **두 시계열의 통계적 동조 정도만 보여줍니다**. 인과 관계의 증거가 아닙니다. This chart shows **statistical co-movement only** — not evidence of causation.

### 자주 발생하는 spurious 상관의 원인 / Common sources of spurious correlation

- **비정상성 (Non-stationarity)** — 두 시계열이 모두 추세를 가지면 추세 자체가 상관을 만듭니다. 응답의 `non_stationary_suspected` 경고는 ADF (Augmented Dickey-Fuller) 검정에서 도출됩니다.
- **자기상관 (Autocorrelation)** — 단일 시계열 내 시간적 자기상관이 lag CCF의 분산을 부풀리고 가짜 peak을 만들 수 있습니다.
- **혼동 변수 (Confounders)** — 관측되지 않은 제3의 변수가 X와 Y를 동시에 움직이게 할 수 있습니다 (예: 외부 지정학 사건).
- **식별/포함 관계 (Identity/containment)** — `reports.total`과 `reports.by_group.<g>` 같은 경우, g가 corpus를 거의 전부 차지하면 r ≈ 1.0이 자명하게 나옵니다. `identity_or_containment_suspected` 경고가 95% 임계 초과 시 트리거됩니다.

### 인과 추론을 위해서는 / For causal inference

- 도구 변수 (Instrumental variables)
- Regression discontinuity
- Difference-in-differences
- 외부 충격을 활용한 자연 실험 / Natural experiments

본 도구는 위 분석의 **선행 단계** — 후보 관계를 식별하기 위한 탐색 도구로 사용하세요. This tool is the **first step** before the above analyses — use it to surface candidate relationships, not to confirm them.

---

## 6. 경고 코드 사전 / Warning code reference

| 코드 / Code | 트리거 / Trigger | Severity |
|:---|:---|:---|
| `non_stationary_suspected` | 한쪽 또는 양쪽 시계열이 ADF α=0.05에서 정상성 거부 / one or both fail ADF at α=0.05 | `warn` |
| `outlier_influence` | lag=0에서 Pearson과 Spearman의 \|Δr\| > 0.2 | `info` |
| `sparse_window` | `effective_n ∈ [30, 36)` — 임계 바로 위 / just above threshold | `info` |
| `cross_rooted_pair` | X는 reports-rooted, Y는 incidents-rooted (또는 반대) | `info` |
| `identity_or_containment_suspected` | 한 시계열이 다른 시계열의 ≥95% 차지 / one accounts for ≥95% of the other | `warn` |
| `low_count_suppressed_cells` | R-16 disclosure-suppression 발화 / R-16 suppression fired | `info` |

---

## 7. 무엇을 계산하지 않는가 / What we don't compute

본 슬라이스에서 명시적으로 제외 / Explicitly out of scope for D-1:

- **Granger causality / vector autoregression** — Phase 4
- **Transfer entropy, mutual information** — out
- **Pre-whitening / ARIMA residuals** — out (자기상관 보정은 미래 슬라이스)
- **Confidence intervals on r** — p-value만 반환 / only p-values returned
- **Bootstrap CIs for r** — out

---

## 8. 한계 / Limitations

- **N≥30 최소 표본**: 작은 N에서는 BH-FDR이 거의 모든 셀을 거부할 수 있습니다. Conservative N≥30 keeps results interpretable.
- **단일 lag window**: `[-24, +24]`로 고정. 더 긴 또는 짧은 윈도우는 미래 슬라이스. Variable windows are a future slice.
- **카탈로그 시리즈만 지원**: 임의 두 시계열 (e.g. 자유 필터) 은 미래 슬라이스의 power-user surface. Arbitrary series are a future slice.
- **R-16 disclosure suppression**: 월별 raw count < 5인 셀은 `low_count_suppressed`로 마스킹됩니다. 작은 카테고리(국가/섹터)에서 cell이 많이 빠질 수 있습니다.

---

## 9. 변경 이력 / Change log

- 2026-05-03 — 초판 / Initial version, ships with PR #28 (D-1 BE primitives).

---

> 본 페이지의 lag 방향 문장 "Positive lag = X leads Y by k months."은 R-13 prevention test의 검증 대상입니다. 변경 시 i18n 키 `correlation.lag.direction_sentence` 와 R-13 테스트도 함께 갱신해야 합니다. The lag-direction sentence above is asserted by R-13 prevention tests; update i18n key + R-13 test together.

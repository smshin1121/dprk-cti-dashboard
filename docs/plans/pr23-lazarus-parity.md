# PR #23 — lazarus.day feature parity

**Status:** 🔒 **Locked — 2026-04-24, amended 2026-04-25** (OI-A/B flip: B→A). OI-A / OI-B = A (new `GET /api/v1/analytics/incidents_trend?group_by=motivation|sector` endpoint — fact-table mismatch with `compute_trend` surfaced at Group A C1 pre-kickoff forced the flip; see §9 status log). OI-C = A (extend `/dashboard/summary` with `top_sectors`). OI-D = A (aggregate on existing `sources.name` — see §2.5 below; no new `contributors` table). OI-E = B (author autocomplete). OI-F = B (year → date range synthesis in FE; URL_STATE_KEYS 5-tuple preserved). OI-G = A (quote deferred). OI-H = B (detail-page external link to lazarus.day). OI-I = A (parity before visual). OI-J = A (Phase 3.5).

**Base:** `chore/expose-dev-ports` (PR #22 open, pending merge). Per user 2026-04-24 OK: "머지 전이라도 그 브랜치 위에서 병렬 작업하는 판단도 괜찮습니다." — branch `feat/p3.5-lazarus-parity` off `chore/expose-dev-ports`; rebase onto `main` after chore merges.

**Source of intent:** lazarus.day is a public Lazarus-APT tracker ("lazarusholic, a big fan of Lazarus") that almost certainly is where the v1.0 workbook originated — row counts line up (our bootstrap yielded 227 actors vs their 228; 3,435 reports vs their ~3,527; 215 incidents vs their 217). Treating it as our canonical feature reference is a defensible anchor.

**Scope boundary:** BE + FE. Zero Keycloak / OIDC changes. No new ingest sources. No LLM surface change. Data contracts may grow additively (new endpoints, new DTO fields) — existing contracts stay stable (§0 invariant #1).

**Mapping to design doc v2.0:**

- §5.3 [C] WorldMap — already covered
- §5.2 [B] KPI strip — already covered
- §5.4 [D] ATT&CK Heatmap — **exceeds** lazarus.day (they don't have ATT&CK)
- §6.1 F-1 similarity — **exceeds** (they don't have pgvector similar)
- §6.1 F-4 geopolitical correlation — not in either; not this PR
- §14 Phase 3 Analytics Depth — this PR slots as **Phase 3.5** (between Phase 3 detail views and Phase 4 LLM automation), capturing the analytic breakdowns lazarus.day has that we don't

---

## 0. Lock summary (pinned invariants)

Three lines that survive implementation debate:

1. **"Parity" = behavioral equivalence, not visual replica.** We match what lazarus.day *shows the user*, not how it paints pixels. Visual language is PR #22's job. Empty parity means: a user coming from lazarus.day does not notice a missing analytic — every chart/filter/breakdown they know has an equivalent.
2. **Zero existing contract regression.** All PR #10-#21 endpoints / shapes / testids preserved. New endpoints are net-add. FE filter semantics grow; existing filter keys unchanged (URL_STATE_KEYS 5-tuple respected; additions are new keys, not renames).
3. **Slug compatibility is a choice, not a requirement.** lazarus.day uses `/reports/post/<kebab-slug>` and `/actors/alias/<kebab-alias>`. Our current routes are `/reports/:id` (int) and `/actors/:id` (int). Decision OI-S locks whether we mirror slugs (BE resolver + FE router change) or document the divergence and link from our detail pages to the upstream slug.

---

## 1. Goal

Close the functional gaps between lazarus.day and the current DPRK CTI dashboard by shipping the analytic breakdowns + filters + minor content features they have and we don't, without touching the dimensions where we're already ahead (auth, similar reports, ATT&CK heatmap, DQ gate, TAXII ingest, i18n, dark mode, URL state).

**Non-goals:**

- Visual redesign (PR #22 owns this — runs after parity)
- Net-new analytics not present in lazarus.day (Phase 3 W1/W2 network/attribution graph, F-4/F-5 geopolitical + CVE — separate)
- Exports (PDF / STIX / CSV — lazarus.day doesn't ship these; they're §14 Phase 5 and stay there)
- Real-time / WebSocket (lazarus.day is periodic static; our current RSS/TAXII pipeline already covers ingest)
- Replacing our int-PK router shape wholesale

---

## 2. Site inventory (2026-04-24 snapshot)

### 2.1 Route map

```
/               home            (search + 3 KPIs + quote + reports section + incidents section + worldmap)
/actors/        list            (228 total, rendered via custom #canvas + #label + #named_by widget)
/actors/alias/<slug>  detail    (per-actor page — not yet inspected; linked from list)
/reports/       list            (241 for 2026, paginated, year + author filters, details at /reports/post/<slug>)
/reports/<year>       list      (filtered by year)
/reports/author/<name>   list   (filtered by author / source)
/reports/post/<slug>  detail    (full article)
/incidents/     list            (217 total, has #trends chart on top)
/incidents/<id?>  detail        (likely — not confirmed from home scrape)
/search/        form            (single text input `name=q`, GET / server-side search)
```

### 2.2 Home page widgets (in render order)

| # | Widget ID | Visual | Data shape | Our equivalent |
|:---:|:---|:---|:---|:---|
| 1 | (form) | Search bar | text query | `⌘K` palette + `/search` (we have) |
| 2 | `#actors / #reports / #incidents` | 3 count KPIs (clickable to lists) | single scalar each | `KPIStrip` 5-card (we have) |
| 3 | `#quote / #author` | Rotating pull-quote + attribution | random pick from a corpus | **GAP** — we have no quote feature |
| 4 | `#numberofreports` | Annual reports bar chart | year → count | `YearBar` (we have) |
| 5 | `#contributors` | Leading Contributors list | author → count, ranked | **GAP** — no contributor aggregation |
| 6 | `#numberofincidents` | Annual incidents bar chart | year → count | Dashboard summary `incidents_by_year` (we have) |
| 7 | `#mtrends` | Annual × Motivation stacked time series | year × motivation → count | **GAP** — `MotivationDonut` is non-temporal |
| 8 | `#strends` | Annual × Sector stacked time series | year × sector → count | **GAP** — we have no sector breakdown at all |
| 9 | `#motivations` | Motivations ranked breakdown | motivation → count | `MotivationDonut` (we have, roughly equivalent) |
| 10 | `#sectors` | Target Sectors ranked breakdown | sector → count | **GAP** |
| 11 | `#locations` | Locations ranked breakdown | country → count | `WorldMap` covers geographic, but **no ranked list widget** |
| 12 | `#worldmap` | World map incidents | country → count | `WorldMap` (we have) |

### 2.3 List-page filters (lazarus.day)

**`/reports/`:**
- Year dropdown (2009–2026, "current year" default)
- Author/Source dropdown (AnyRun, Arkm, BreakGlassIntelligence, Chainalysis, Expel, FalconFeeds, KelpDAO, LayerZero, meowmfer, … ~40+)

**`/actors/`, `/incidents/`:**
- Inspection shows a `#canvas` + `#label` + `#named_by` pattern suggesting a visualization rather than flat list — likely a force-directed graph or interactive map

### 2.4 Tech stack (for reference, not to copy)

- jQuery 3.6.3, ApexCharts 3.41, D3 3.5.17, Datamaps 0.5.9 (TopoJSON 1.6.20)
- Server-rendered (Jinja-like), static home bar the chart JS hydration
- CC-BY-SA 4.0 licensed content

Our stack (React + Vite + Tailwind + recharts + visx) is not changing; feature equivalence, not tooling.

### 2.5 Scope correction (discovered 2026-04-24 post-OI-lock)

Surveyed the existing data model before expanding §6: `reports.author` does **not** exist as a scalar text field. Our schema uses `reports.source_id → sources.name` (FK + junction). lazarus.day's "Author" dropdown labels (Mandiant, Chainalysis, AnyRun, FalconFeeds, …) map directly to our `sources.name`.

**Consequences:**

- **OI-D = A is even cheaper than planned.** No text-canonicalization pass needed — sources are already deduplicated at ingest time (upsert on `sources.name`).
- **Reports "author filter" already exists.** `/api/v1/reports?source=Mandiant` has worked since PR #11 (see `routers/reports.py:197` — `source` is a repeatable Query param). The gap is **FE UX** (no author picker in FilterBar), not BE.
- **"Leading Contributors" aggregation = `GROUP BY sources.name`** over `reports` — one-query addition to `dashboard_aggregator.py`, piggybacking on `/dashboard/summary`.
- Group A scope shrinks: one compute function + one new summary field + one migration-free OpenAPI update.
- Group D scope shrinks: no new query param, no new BE work — only FE autocomplete picker.

---

## 3. Gap map (5 axes per user directive)

### 3.1 기능 목록 (Feature list)

| Feature | lazarus.day | Ours | Verdict |
|:---|:---:|:---:|:---|
| Full-text search | ✓ form | ✓ palette + hybrid /search | **≥** |
| KPI count cards | ✓ 3 cards | ✓ 5-card | **≥** |
| Rotating quote | ✓ | ✗ | **GAP (small)** |
| Annual reports bar | ✓ | ✓ | = |
| Leading contributors | ✓ | ✗ | **GAP (medium)** |
| Annual incidents bar | ✓ | ✓ | = |
| Annual by motivation (stacked) | ✓ | ✗ (have donut) | **GAP (medium)** |
| Annual by sector (stacked) | ✓ | ✗ | **GAP (medium)** |
| Motivations ranked | ✓ | ✓ (donut) | = |
| Sectors ranked | ✓ | ✗ | **GAP (medium)** |
| Locations ranked | ✓ | ✗ (map only) | **GAP (small)** — ranked list under map |
| World map | ✓ | ✓ | = |
| Actors list | ✓ 228 | ✓ 227 | = |
| Actor detail | ✓ slug | ✓ int | = (format differs) |
| Reports list | ✓ 3,527 | ✓ 3,435 | = |
| Report detail | ✓ slug | ✓ int | = (format differs) |
| Reports year filter | ✓ | ✗ (date range) | **GAP (small UX)** |
| Reports author filter | ✓ | ✗ | **GAP (medium)** |
| Incidents list | ✓ 217 | ✓ 215 | = |
| ATT&CK heatmap | ✗ | ✓ | **+Ours** |
| Similar reports (pgvector) | ✗ | ✓ | **+Ours** |
| Dashboard commands (⌘K beyond search) | ✗ | ✓ 7 commands | **+Ours** |
| Auth + RBAC | ✗ public | ✓ Keycloak OIDC | **+Ours** |
| i18n ko/en | ✗ en | ✓ | **+Ours** |
| Dark mode | ✗ light-only | ✓ toggle | **+Ours** |
| URL state sync | ✗ minimal | ✓ 5-tuple | **+Ours** |
| DQ gate | ✗ | ✓ | **+Ours** |
| TAXII ingest | ✗ | ✓ | **+Ours** |
| Review/promote staging | ✗ | ✓ | **+Ours** |

**Net:** 6 GAPs (1 small-feature, 4 medium-analytic, 1 UX-polish) against 12 "+Ours" advances.

### 3.2 정보 구조 (Information architecture)

- lazarus.day: 4 routes + 2 slug-detail patterns. Home is chart-dense, flat nav.
- Ours: 4 routes + 3 int-detail patterns + dashboard is chart-dense + Shell chrome + FilterBar + UserMenu.

**Gap:** None structurally. Our IA is a superset.

### 3.3 필터 / 검색 (Filter + search)

- lazarus.day: `/reports/` has year + author dropdowns. Elsewhere no filters.
- Ours: FilterBar (date range + group + TLP) shared across dashboard + lists. `/search` with hybrid FTS + vector.

**Gap:** **year filter** (cosmetic — derivable from date range) + **author filter** (new FE + BE: filter `reports.author`).

### 3.4 시각화 (Visualization)

- lazarus.day: bar charts (ApexCharts), ranked breakdowns (Motivations / Sectors / Locations), world map (Datamaps), stacked time series (Motivation × Year, Sector × Year), leading-contributor list.
- Ours: KPI strip, WorldMap (@visx/geo Mercator), ATT&CK heatmap, Trend line, Motivation donut, Year bar, Groups mini-list, Report feed, Similar reports panel.

**Gap:**
- **Sector breakdown** (ranked + stacked-time-series) — new BE aggregation over `incident_sectors` junction
- **Motivation × Year stacked** — new BE aggregation combining time + motivation (we have `/analytics/trend` time + `/dashboard/summary` motivation, but not the cross)
- **Locations ranked list** — likely cheap; derive from `/analytics/geo` response with sort + limit
- **Leading Contributors list** — new BE aggregation over `reports.author`

### 3.5 내보내기 (Export)

- lazarus.day: **none**. The site doesn't export. Designed for browse + read, CC-BY-SA attribution.
- Ours: **none currently**. Design doc §14 Phase 5 schedules STIX 2.1 export + PDF briefing.

**Gap:** None for parity purposes. Exports remain Phase 5 work.

### 3.6 실시간성 (Real-time)

- lazarus.day: updates periodically (Patreon-funded manual curation; no live feed).
- Ours: RSS + TAXII Prefect workers (design doc §3.3) — more real-time than theirs.

**Gap:** None. We're ahead.

---

## 4. Scope decision matrix (must-match vs skip)

| Gap | Verdict | Justification |
|:---|:---:|:---|
| Leading Contributors | **MUST** | Core attribution signal; cheap BE aggregation; highly visible on home page |
| Annual × Motivation stacked | **MUST** | Completes the motivation story (we have static + static); temporal motivation shift is a narrative we currently obscure |
| Annual × Sector stacked | **MUST** | Sector is a first-class filter dimension per §5.1 persona list; missing it entirely is a real gap |
| Sectors ranked breakdown | **MUST** | Part of same data as stacked; cheap extension |
| Locations ranked list | **SHOULD** | WorldMap already conveys the info; ranked list is UX redundancy for accessibility |
| Reports author filter | **MUST** | Already a column; filter is a trivial query param add |
| Reports year filter | **MAY** | Derivable from date range; add as a UX convenience if implementation is cheap |
| Rotating quote + author | **MAY** | Small, charming, quotes need a corpus — defer until a corpus exists |
| Slug URLs | **SKIP** | Int-PK routes work; map to slugs via backend `slug → id` resolver only if SEO or external-link parity becomes a priority (not now) |

4 MUST, 1 SHOULD, 3 MAY/SKIP.

---

## 5. Decisions (to be locked)

### 5.1 Open items — LOCKED 2026-04-24

| ID | Locked | Rationale |
|:---:|:---:|:---|
| **OI-A** | **A** — new `GET /api/v1/analytics/incidents_trend?group_by=motivation` endpoint | **Flipped 2026-04-25.** Fact-table mismatch discovered at Group A C1 pre-kickoff: `compute_trend` is reports-based (`COUNT(DISTINCT reports.id)` bucketed by `month(reports.published)`), but lazarus.day `#mtrends` is incidents-based (`incident_motivations` junction keys off `incidents.id`, not `reports.id`). Extending `compute_trend` with `group_by` would bifurcate it into reports-fact OR incidents-fact — semantic muddiness bleeding into OpenAPI + Pact + FE hook shape. New endpoint preserves single-responsibility on `/analytics/trend` (15 existing Pact interactions **untouched** — stronger guarantee than extension) + has its own `IncidentsTrendResponse` envelope with no conditional shape. |
| **OI-B** | **A** — same new endpoint, `group_by=sector` | Parallel axis on `incident_sectors` junction; same `IncidentsTrendResponse` envelope. Flipped together with OI-A for the same fact-table reason. |
| **OI-C** | **A** — extend `/dashboard/summary` with `top_sectors` | Mirrors the existing `top_motivations` precedent (see `schemas/read.py:351`). Additive field; OpenAPI snapshot grows by ~500B. |
| **OI-D** | **A** (REVISED per §2.5) — aggregate on existing `sources.name` | No `reports.author` field exists; our schema already has `sources` FK + junction. No new table, no migration. |
| **OI-E** | **B** — autocomplete input | ~40+ distinct sources per lazarus.day inventory; dropdown too dense. Needs `/api/v1/sources?q=<prefix>` endpoint (new, thin). |
| **OI-F** | **B** — synthesize year → date range in FE | URL_STATE_KEYS 5-tuple (`date_from`, `date_to`, `group_id`, `view`, `tab`) preserved. Zero test-contract breakage. |
| **OI-G** | **A** — defer quote | No corpus; not worth scope expansion for a charming-but-non-analytic feature. |
| **OI-H** | **B** — external link from detail pages | Each `/reports/:id`, `/incidents/:id`, `/actors/:id` page gets an "View on lazarus.day" secondary action (when a slug mapping exists). No router change. Slug resolver requires knowing lazarus.day's slug format — deferred. |
| **OI-I** | **A** — parity (#23) before visual (#24) | Avoids re-skinning a surface that's about to grow new widgets. |
| **OI-J** | **A** — Phase 3.5 | Analytics depth completion. Fits between Phase 3 detail views and Phase 4 LLM automation. |

### 5.2 Dependent items — derived 2026-04-24

- **DP2** DashboardSummary envelope growth — `top_sectors: list[DashboardSectorCount]` added (Field default_factory=list). Mirrors `incidents_by_motivation` shape. Zero `group_by` flag required (always present; empty if no data).
- **DP3** New endpoint `/api/v1/sources?q=<prefix>&limit=<n>` (role-gated read, 60/min) returns `{items: [{id, name, report_count}]}` sorted by report_count DESC. Limit ≤ 50 default 20.
- **DP4** Pact contract: 4 new interactions — `incidents_trend?group_by=motivation populated`, `incidents_trend?group_by=sector populated`, `summary with top_sectors populated`, `sources autocomplete populated`. Keeps pact interaction count at 18 + 4 = 22. `/analytics/trend` (15 existing flat-shape interactions) **untouched**.
- **DP5** FE Zod: new `incidentsTrendResponseSchema` + `incidentsTrendBucketSchema` + `incidentsTrendSeriesItemSchema` (existing `trendResponseSchema` unchanged); `dashboardSummarySchema` gets `top_sectors`; new `sourceSuggestionsSchema`.
- **DP6** FE hook: new `useIncidentsTrend({ groupBy: 'motivation' | 'sector' })` — React Query key `['incidents_trend', groupBy, filters]`; existing `useTrend` hook and query key untouched.
- **DP7** FE FilterBar: `<SourcePicker/>` component with async autocomplete. Filter state key: `sources` (list[str]) — already passed to `/reports?source=...`. No URL_STATE change (filter key stays in filterStore local scope per PR #13 convention).

---

## 6. Groups — detailed post-lock (2026-04-24)

### 6.A — Backend aggregation layer (3 commits)

**C1** — new `GET /api/v1/analytics/incidents_trend` endpoint + new `compute_incidents_trend` aggregator in `services/api/src/api/read/analytics_aggregator.py`. **`/analytics/trend` not touched.**
- Signature: `compute_incidents_trend(filters: IncidentFilters, group_by: Literal["motivation", "sector"]) -> IncidentsTrendResponse`. `group_by` is **required** (no flat mode — that's what `/analytics/trend` is for).
- Fact table: `incidents` (NOT `reports`). `COUNT(DISTINCT incidents.id)` bucketed by `date_trunc('month', incidents.reported)`. `incidents.reported` is nullable (see `tables.py:267`) — apply `WHERE incidents.reported IS NOT NULL` upstream of the junction join, consistent with the list-endpoint cursor convention (`tables.py:258-261`).
- `group_by="motivation"` branch: `LEFT JOIN incident_motivations ON incident_motivations.incident_id = incidents.id`. `GROUP BY (date_trunc('month', reported), motivation)`. Rows with no motivation assignment land in a sentinel `"unknown"` key (never dropped). Outer monthly `count` is `COUNT(DISTINCT incidents.id)`; `series` entries count category memberships, so multi-motivation incidents may make `sum(series[*].count)` exceed outer `count`.
- `group_by="sector"` branch: same shape, `incident_sectors` junction; same unknown-bucket handling.
- Response envelope: `IncidentsTrendResponse { buckets: list[IncidentsTrendBucket], group_by: str, generated_at: datetime }` where `IncidentsTrendBucket = { month: date, count: int, series: list[IncidentsTrendSeriesItem] }` and `IncidentsTrendSeriesItem = { key: str, count: int }`. **Distinct Pydantic type from `TrendResponse`** — no conditional-shape union, no FE discriminated-union cost.
- `group_by` validator: FastAPI `Query(...)` with `Literal["motivation", "sector"]` → 422 on invalid; `Query(...)` (required) → 422 on missing.
- Filter propagation: reuse the same `IncidentFilters` assembly used by `compute_dashboard_summary`'s incidents side (date_from / date_to / group_ids / tlp). Extract the shared helper if it doesn't already exist; do **not** duplicate filter logic.
- Rate limit: reuse the read bucket on `/analytics/*` (currently 60/min per-user per `routers/analytics.py`).
- OpenAPI examples: `group_by=motivation` populated (3 months × 4 motivations) + `group_by=sector` populated (3 months × 3 sectors) + empty (`buckets: []`).

**C2** — `compute_dashboard_summary` extended with `top_sectors: list[DashboardSectorCount]` (N=10 cap per plan D6 top_n=5 default; expose as param). Pure SQL: `SELECT sector, COUNT(DISTINCT incident_id) FROM incident_sectors JOIN incidents ... WHERE date/group filters ... GROUP BY sector ORDER BY count DESC LIMIT top_n`.

**C3** — New route `GET /api/v1/sources?q=<prefix>&limit=<n>` + `compute_sources_suggestions` aggregator.
- Query: prefix match `sources.name ILIKE q || '%'` OR full-text contains (decide at implementation). Limit 1–50, default 20. Also compute `report_count` per source via LEFT JOIN `reports` GROUP BY `sources.id, sources.name`.
- Response: `{items: [{id, name, report_count}]}` sorted by `report_count DESC, name ASC` (stable).
- Rate limit: 60/min per-user (reuse read bucket).
- OpenAPI examples: populated (3 sources) + empty (q doesn't match).

**Sub-criteria (pre-landing review, in-commit assertions):**

- **C1.a** zero regression on `/analytics/trend` — by construction: **no code touched** on that endpoint; 15 existing Pact interactions reverify identically. Grep-assertion that `compute_trend` signature + docstring are byte-identical to the PR-parent commit.
- **C1.b** `group_by=motivation` and `group_by=sector` each produce distinct outer monthly counts, unknown-bucket preservation, and an explicit multi-junction regression where `sum(series[].count)` can exceed outer `count` (unit test on aggregator + integration test against real PG)
- **C1.c** 2 new Pact interactions on `/api/v1/analytics/incidents_trend` (motivation populated + sector populated). Empty response is a top-level shape: `buckets: []` (no `series: null` question to answer — the new envelope has no conditional field).
- **C1.d** `group_by` **required**: request without query param → 422; invalid value (`"foo"`) → 422. Regression tests for both paths.
- **C1.e** static-source scan: new endpoint gated by `_READ_ROLES` + 60/min limiter (grep assertion, per `pattern_factory_wiring_guard` precedent)
- **C2.a** DashboardSummary snapshot regeneration; OpenAPI grows by ~500B
- **C2.b** `top_sectors` respects `group_ids` filter same way `incidents_by_motivation` does (filter-propagation audit)
- **C3.a** sources endpoint returns empty list (not 404) when no match
- **C3.b** static-source scan: new endpoint is gated by `_READ_ROLES` + `_limiter.limit("60/minute")` — grep assertion

### 6.B — FE client layer (2 commits)

**C4** — Zod schema evolution:
- New `incidentsTrendSeriesItemSchema` + `incidentsTrendBucketSchema` + `incidentsTrendResponseSchema` (`trendResponseSchema` unchanged — no edits)
- `dashboardSummarySchema` gains `top_sectors: z.array(dashboardSectorCountSchema).default([])`
- New `sourceSuggestionSchema` + `sourcesResponseSchema`
- Literal parity test against BE OpenAPI examples (reuses PR #17 D-C pattern).

**C5** — Hook + endpoint layer:
- New `useIncidentsTrend({ groupBy: 'motivation' | 'sector' })` — React Query key `['incidents_trend', groupBy, filters]`; existing `useTrend` hook and query key untouched
- `useDashboardSummary` unchanged structurally; consumers read new `top_sectors` field
- `useSourceSuggestions(q: string)` — debounced 250ms, enable-gate `q.length >= 2`
- `queryKeys.incidentsTrend(groupBy, filters)` + `queryKeys.sourceSuggestions(q)` factories
- Pact consumer adds 4 new interactions (OpenAPI parity).

### 6.C — FE dashboard widgets (4 commits)

**C6** — `ContributorsList` widget → derives from `/dashboard/summary.top_sources` (from OI-D + DP2 — wait, `top_sectors` is the new field; "Leading Contributors" is a **separate** new field `top_sources`). **Correction: DP2 covers `top_sectors`; `top_sources` is a SECOND new field. Update C2 to add both.**
- Row: `{source_name, report_count, latest_report_date}` → i18n-friendly list, links to `/reports?source=<name>` (filter deep-link, OI-H-adjacent)

**C7** — `MotivationStackedArea` widget — consumes `useIncidentsTrend({ groupBy: 'motivation' })`. Recharts StackedAreaChart with color palette from PR #24 chart theme placeholder (default Tailwind for now; Group A of PR #24 will sub in Paul Tol colors).

**C8** — `SectorStackedArea` widget — consumes `useIncidentsTrend({ groupBy: 'sector' })`. Same Recharts StackedAreaChart shape as C7. Mounts next to MotivationStackedArea in dashboard grid.

**C9** — `SectorBreakdown` widget — consumes `summary.top_sectors`. Horizontal bar list mirroring existing `MotivationDonut` positioning.

**C10** — `LocationsRanked` widget (lightweight — SHOULD per §4) — consumes existing `/analytics/geo` response, sorts by `incident_count DESC`, limits to 10, renders as ranked list. Mounts below `WorldMap`.

**C11** — DashboardPage §4.2 grid extension: integrate 5 new widgets into existing rows. No structural re-layout (PR #13 grid pinned). Plan decision: add new row between existing `[C] WorldMap` row and `[D] ATT&CK heatmap` row — "time-series breakdowns" band.

### 6.D — Author (source) filter in FilterBar (2 commits)

**C12** — `<SourcePicker/>` autocomplete component on FilterBar.
- Input + async dropdown using `useSourceSuggestions`
- Multi-select (chips) — matches our existing group/tag filter UX
- Writes to `useFilterStore.sources: list[str]`, which is already consumed by `toReportListFilters` → `/reports?source=...`
- Zero URL_STATE_KEYS change (the sources filter lives only in filterStore, not URL — matches tag behavior).

**C13** — Report list deep-link mapping:
- ContributorsList row click → navigate to `/reports` with `sources=<name>` pre-filled in filterStore
- Integration test: clicking a contributor row lands `/reports` with the source filter pre-populated.

### 6.E — Detail-page external lazarus.day link (1 commit)

**C14** — Add `<a href="https://lazarus.day/reports/post/<slug>">View on lazarus.day</a>` link to `/reports/:id` detail page footer. Slug format not inferable from id — add an optional `external_slug` field on ReportDetail (populated by matching `url_canonical` against a `lazarus.day` pattern OR leaving None; OI-H is "link when possible, not always"). Actor + incident detail follow same pattern.

### 6.F — Verification (1-2 commits)

**C15** — Regression suite:
- `data-testid` parity scan — added (net), deleted (0)
- URL_STATE_KEYS 5-tuple assertion test re-run — no change required since source filter doesn't use URL state
- Pact 15 existing + 4 new = 19 interactions verify green
- OpenAPI snapshot diff shows only additive fields (grep assertion: no removed fields, no renamed paths)
- DQ smoke: manual `top_sectors` SQL against a real-PG smoke DB — result count sanity

Approx: 15 commits across 6 Groups. Memory `feedback_codex_iteration.md` says 3-6 rounds for substantive PRs — budget 3 rounds.

---

## 7. Risks

| ID | Risk | Mitigation |
|:---:|:---|:---|
| R1 | `reports.author` is text → same author may have drift (`"AhnLab"` vs `"AhnLab ASD"`) inflating contributor counts | OI-D = B (contributors lookup table with alias mapping) moves this into data model; OI-D = A accepts the noise + adds a text-canonicalization pass in aggregation layer |
| R2 | Stacked-time-series chart rendering (motivation × year, sector × year) may push Lighthouse perf below baseline | Group F measures; fallback: sparse data (≤20 categories × 18 years = 360 cells — recharts handles easily) |
| R3 | URL_STATE_KEYS 5-tuple pin broken by year filter addition | OI-F = B (synthesize from date range) preserves pin; OI-F = A formally grows to 6-tuple and updates every assertion test |
| R4 | Motivation/sector/location slugs on lazarus.day may not match our normalized values (e.g. their "Espionage" vs our "Espionage" case) | Group A aggregation layer includes normalization; Pact provider-state uses canonical values |
| R5 | Phase ordering confusion — PR #22 visual would re-skin surfaces that PR #23 changes | OI-I = A answers this; visual redesign runs after parity is shipped to avoid double-rework |

---

## 8. Predecessors / Successors

**Predecessor:** `chore/expose-dev-ports` (open PR, pending merge) — provides host-hybrid dev loop needed for iterating on new FE widgets.

**Successor:** **PR #22 visual redesign** — if OI-I = A, PR #22 re-skins a surface that includes PR #23's new widgets. Planning order inversion from 2026-04-23 (when PR #22 was drafted first) to 2026-04-24 (parity first) is the direct consequence of user directive on 2026-04-24.

**Design doc adjustment:** add this PR to §14 as a Phase 3.5 line ("Analytics depth completion — lazarus.day parity") so roadmap tracking matches reality.

---

## 9. Status log

- **Draft v1 — 2026-04-24.** lazarus.day inventory captured. Gap map published. OI-A – OI-J open. Awaiting user answers to lock §5.1 → expand §6 Group details → begin Group A.
- **Locked — 2026-04-24.** All OIs locked to recommended defaults (`B / B / A / A / B / B / A / B / A / A`). §2.5 scope correction recorded: `reports.source_id → sources.name` is the "author" surface; no new table. §5.2 DP1–DP7 derived. §6 Groups A–F expanded to concrete pre-landing criteria C1–C15. Branch name: `feat/p3.5-lazarus-parity` off `chore/expose-dev-ports`. PR #22 (visual redesign) plan doc to be renumbered PR #24.
- **Amended — 2026-04-25.** OI-A/B flip: **B → A**. New OI vector: `A / A / A / A / B / B / A / B / A / A`. Trigger: fact-table mismatch surfaced at Group A C1 pre-kickoff — `compute_trend` is reports-based (`COUNT(DISTINCT reports.id)` on `month(reports.published)`), but lazarus.day `#mtrends`/`#strends` are incidents-based (`incident_motivations` / `incident_sectors` junctions key off `incidents.id`). Extending `compute_trend` with a `group_by` param would bifurcate it into reports-fact-OR-incidents-fact depending on caller — muddiness propagates to OpenAPI, Pact, and FE hook shape. Rejected. Locked instead: new dedicated `GET /api/v1/analytics/incidents_trend?group_by=motivation|sector` endpoint with its own `IncidentsTrendResponse` envelope. Diff vs original lock: §5.1 OI-A/B rows rewritten; §5.2 DP1 deleted (DP4/DP5/DP6 updated to reference new endpoint/schemas/hook); §6.A C1 + sub-criteria (C1.a–C1.e) rewritten; §6.B C4/C5 updated; §6.C C7/C8 hook consumer updated. `/analytics/trend` (15 existing Pact interactions) **untouched** — stronger regression guarantee than the original extension plan. Validates `pattern_scope_expansion_before_criteria_lock` for the third time in this PR (§2.5 reports.author → sources.name was #2).

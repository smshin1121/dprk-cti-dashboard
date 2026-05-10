# lazarus.day data parity — methodology + audit log

**Purpose.** Track row-count and attribution-coverage parity between this
repository and the public upstream tracker `https://lazarus.day` (the
"lazarusholic" DPRK threat-actor reference dashboard). PR #23 closed the
*feature* parity gaps (5 MUST + 1 SHOULD analytic widgets); this document
governs the *data* parity check that follows behind shipped features.

This is a methodology + audit log — feature/widget parity belongs in
`docs/plans/pr23-lazarus-parity.md`. New row-count audits append a new
dated section to §3 below; do not create per-audit files.

---

## 1. Counting semantics — important caveat before any comparison

Raw `COUNT(*)` on our tables is **not** comparable to the headline numbers
on lazarus.day. The counting models differ across all three entities,
and only one of the three (incidents) is true apples-to-apples.

### 1.1 Actors / groups

| Property | Us (`groups` table) | lazarus.day |
|:---|:---|:---|
| Row granularity | one canonical group | one researcher-naming-convention |
| Aliases | stored inside `aka[]` array column | each alias is its **own row** |
| Example: "Lazarus" | 1 row, name=`Lazarus Group`, `aka=['APT38','Hidden Cobra',...]` | many rows: `APT-C-26`, `APT-Q-1`, `CitrineSleet`, `Bureau121`, `Hidden Cobra`, `APT38`, ... — all with AKA=`Lazarus` |
| What the count measures | distinct DPRK threat groups | distinct researcher-tracking-identities across CTI vendors |

A user comparing `groups.count` to lazarus.day's "Total 228 actors"
header will see a 30× gap that is **not** a data deficit — it is a
counting-model mismatch. To compare like-for-like, expand our `aka[]`
arrays into individual rows, or normalize lazarus.day's set by
deduplicating against a canonical AKA group.

### 1.2 Reports

| Property | Us (`reports` table) | lazarus.day |
|:---|:---|:---|
| Row granularity | one ingested feed item | one curated landmark report |
| Source | RSS + TAXII ingest pipelines (D3, D-9 worker) | manual editorial curation |
| Volume profile | high (every published item) | low (selective) |

These are incommensurable by construction. Raw count gap is meaningless;
the relevant questions are (a) whether a report a user finds on
lazarus.day is also discoverable on our dashboard via `q=` search or
`source=` filter, and (b) whether our additional volume is signal or
noise (review-queue gating handles this elsewhere).

### 1.3 Incidents

| Property | Us (`incidents` table) | lazarus.day |
|:---|:---|:---|
| Row granularity | one named incident / event | one named incident / event |
| Counting model | apples-to-apples | apples-to-apples |

This is the **only** table where raw row count comparison is
meaningful.

---

## 2. Pact-fixture noise — exclude from production-shape numbers

The dev / CI database accumulates rows from `_pact/provider_states`
seeding during contract verification runs. These rows persist by design
(pact-ruby's per-interaction seed model does not clear between
verifications). They must be excluded when computing
production-shape parity numbers.

Filter patterns for the `dprk_cti` development database (post
PR #36 + PR #37 fixture catalog), verified against actual fixture
shape on `main @ a7d78e8`:

```sql
-- groups: real = NOT pact-prefix-named fixture
-- Caveat: assumes the dev DB has been bootstrapped from the v1.0
-- workbook before any pact run. pact_states.py:975/:1206 call
-- _ensure_full_group(name="Lazarus Group", ...) and other handlers
-- upsert real-named canonical rows; in a bootstrapped DB the row
-- pre-exists and the upsert is idempotent, but in a fresh-pact-only
-- DB this filter would yield a phantom "real" row from pact-seeded
-- canonical names. Re-bootstrap before audit if in doubt.
WHERE name NOT LIKE 'pact-%' AND name NOT LIKE 'Pact %'

-- reports: real = NOT pact-test-host fixture URL
-- Pact fixtures use the canonical https://pact.test/... host (see
-- pact_states.py:586/597/607/etc.). Earlier drafts of this filter
-- cited urn:pact-% / urn:fixture% schemes that match zero real
-- rows; the title ILIKE clause is kept as a defensive secondary
-- match for any fixture without a pact.test URL.
WHERE NOT (url LIKE 'https://pact.test/%'
           OR title ILIKE '%pact%fixture%')

-- incidents: real = NOT 'pact' or 'fixture' in title (NULL-safe)
-- incidents.title is NOT NULL per services/api alembic schema, so
-- the COALESCE guard on title is technically redundant. The guard
-- pattern matters when filters extend to incidents.description
-- (nullable) — a previous draft using `description ILIKE ...`
-- silently dropped real rows because `NOT (a OR NULL)` evaluates
-- to NULL, excluding the row from the count.
WHERE COALESCE(title,'') NOT ILIKE '%pact%'
  AND COALESCE(title,'') NOT ILIKE '%fixture%'
```

---

## 3. Audit log

### 3.1 Audit — 2026-05-10 (post PR #37 merge, main @ `a7d78e8`)

Triggered by `phase_status.md` follow-up: "Lazarus.day parity check —
revisit row-count parity comparison after PR #35 enabled actor-network
analytics." Memory anchor `project_lazarus_day_upstream` (last refresh
2026-04-24) carried older numbers (`227 / 3,435 / 215 vs 228 / 3,527 /
217`) that pre-date subsequent ETL refreshes; this audit refreshes them.

#### Headline parity table (production-shape, real-data only)

| Entity | Us (real) | lazarus.day | Gap | Verdict |
|:---|---:|---:|---:|:---|
| Incidents | 215 | 217 | −2 (−0.9%) | **PARITY** |
| Reports (apples-to-apples count meaningless — see §1.2) | 3,438 ingested items | ~272 curated reports | n/a | INCOMMENSURABLE |
| Groups (canonical) | 7 | 228 alias-rows ≈ 15-25 normalized canonical groups | methodological | METHODOLOGY GAP — see §3.1.3 |

#### 3.1.1 Incidents — at parity (215 vs 217)

The only true apples-to-apples comparison sits within 1% of upstream
truth. No action required.

#### 3.1.2 Reports — incommensurable, attribution coverage matters more

Raw count comparison is not informative (see §1.2). The substantive
diagnostic for our reports table is **how many of them are linked to
DPRK threat groups via the `report_codenames` junction**:

| Metric | Count | % |
|:---|---:|---:|
| Real reports total | 3,438 | 100% |
| Reports attributed to a real group via the `report_codenames` junction | 1,135 | **33%** |
| Reports unattributed (no `report_codenames` entry) | 2,320 | 67% |

A 33% attribution rate is consistent with the ingest pipeline's
breadth — feed items often mention DPRK adjacencies (sanctions, regional
news, sector context) without naming a specific actor. Whether that
ratio is healthy or under-attributed is a question for the data quality
audit, not a parity question, and is **out of scope for this document**.

#### 3.1.3 Groups — counting-model mismatch + canonical-coverage observation

Our 7 real canonical groups: `Andariel`, `BlueNoroff`, `Kimsuky`,
`Konni`, `Lazarus`, `Lazarus Group`, `ScarCruft`. Two distinct rows for
"Lazarus" / "Lazarus Group" suggest a normalization opportunity but are
not a parity concern per se.

The 228 lazarus.day rows compress to roughly 15-25 canonical DPRK groups
once researcher-naming-convention duplicates fold (Mandiant APT*, Microsoft
*Sleet, CrowdStrike *Chollima, Qihoo APT-C-*, etc.). Even normalized,
that is roughly 2-3× our canonical coverage. The deltas are likely:

- Subgroup splits we collapse: e.g., Lazarus subgroups
  `StardustChollima`, `RicochetChollima`, `SilentChollima`,
  `CryptoCore` (we keep these as `aka[]` of parent canonical groups)
- Adjacent / derived groups: e.g., `TraderTraitor`, `APT43`,
  `TEMP.Hermit`, `NICKEL ACADEMY`, `Bureau 121`, `UNC1069`, etc.
- Attribution-thin groups that did not survive our curation cut

Whether to expand our canonical-group coverage is a product decision,
not a parity-audit decision. Recorded here as input to the next
roadmap discussion. **Not a 2026-05-10 follow-up commitment.**

#### 3.1.4 Incidents attribution coverage (data-quality observation)

Junction-table attribution coverage on the 215 real incidents:

Each row reports `COUNT(DISTINCT incident_id)` against the unfiltered
junction table; the % column normalizes against the **filtered** count
of 215 real incidents. Junction rows on pact-fixture incidents leak
into the unfiltered numerator (the +5 noted on `incident_motivations`)
without a join to `incidents` to apply the §2 filter, hence "≥ 97%
real" rather than a precise percentage on that row only.

| Junction table | Distinct incidents covered (unfiltered) | % of 215 real |
|:---|---:|---:|
| `incident_motivations` | 220 (~5 fixture-side) | ≥ 97% real |
| `incident_sectors` | 214 | 99% |
| `incident_countries` | 207 | 96% |
| `incident_sources` | **3** | **1.4%** |

The motivation / sector / country junctions are well-populated; these
back PR #23's `MotivationStackedArea`, `SectorStackedArea`,
`SectorBreakdown`, `LocationsRanked` widgets and the data quality
matches the shipped widget claims.

The `incident_sources` coverage at 1.4% is anomalous. PR #23 C6 ships
`ContributorsList` reading `top_sources` aggregated **from the reports
side** (`reports.source` foreign key), not from `incident_sources`, so
the shipped widget is not affected. But if a future widget reads
contributor attribution from the incident side, this gap will surface.
Logged as observation, **not a 2026-05-10 follow-up commitment.**

#### 3.1.5 No `incident_attributions` table — design observation

Incidents have no junction-table edge to the `groups` table. Threat-
actor attribution flows through the report side: `incidents` → (via
shared sector / country / motivation) ← `reports` → `report_codenames`
→ `codenames` → `groups`. This indirection is by design (D-1 aggregator
contracts assume report-side attribution); recorded for future reviewers
who may look for a direct edge.

---

## 4. Re-audit procedure

To refresh this document with a new dated section in §3:

1. Confirm dev DB is up: `docker compose ps db cache keycloak`.
2. Refresh memory anchor `project_lazarus_day_upstream` before relying
   on its numbers — cached values decay each ETL refresh cycle.
3. Run the SQL filters in §2 against `dprk_cti` to compute real-data
   row counts:
   ```sql
   SELECT 'groups_real', COUNT(*) FROM groups
     WHERE name NOT LIKE 'pact-%' AND name NOT LIKE 'Pact %'
   UNION ALL SELECT 'reports_real', COUNT(*) FROM reports
     WHERE NOT (url LIKE 'https://pact.test/%'
                OR title ILIKE '%pact%fixture%')
   UNION ALL SELECT 'incidents_real', COUNT(*) FROM incidents
     WHERE COALESCE(title,'') NOT ILIKE '%pact%'
       AND COALESCE(title,'') NOT ILIKE '%fixture%';
   ```
4. Fetch upstream counts: lazarus.day `/actors/`, `/reports/`,
   `/incidents/` headers (the root `/` page does not show totals).
5. Append a new `### 3.N Audit — YYYY-MM-DD (context)` section.
6. Update memory anchor `project_lazarus_day_upstream` with the
   refreshed numbers + the audit's date.

Append-only convention. Older audits stay in §3 as historical record.

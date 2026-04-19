"""Read surface DTOs for PR #11 Phase 2.2.

Design contracts locked in ``docs/plans/pr11-read-api-surface.md``
§2.1 D3/D6/D9/D10/D11/D12/D13, §2.3 Endpoint/Decision matrix, §3 In
scope (DTO list). The file is deliberately split into three groups
so Group B–E routers only touch the envelope they own:

1. **List item DTOs** — ``ReportItem`` / ``IncidentItem`` / ``ActorItem``.
   Minimal fields per v1.0 §5.4. ``tlp`` is included on ``ReportItem``
   so the DTO shape is already prepared for the Phase 2.3+ AMBER-
   filtering (RLS) work (plan D4 defer). Filtering itself is out of
   PR #11 scope.

2. **List envelopes** — ``ReportListResponse`` / ``IncidentListResponse``
   share ``{items, next_cursor}`` because plan D3 locks both to keyset
   pagination. ``ActorListResponse`` has a different shape
   (``{items, limit, offset, total}``) because plan D3 keeps actors
   on offset pagination. These envelopes are **not** cross-referenced
   — a single "generic list" envelope would need variant fields
   that silently mean different things per endpoint, which Group A's
   review priority flags as a smell to avoid.

3. **Dashboard DTOs** — ``DashboardSummary`` + three aggregate rows.
   ``top_groups`` length is bounded by the D6 ``top_n`` query param
   (min 1, max 20, default 5 — the router enforces the query-side
   bound; this DTO only guarantees the DB-fetched list length never
   exceeds it).

Two cross-cutting rules enforced at DTO layer:

- **Plan D12 — invalid filters → 422 uniformly.** Field bounds are
  declared here (``Field(ge=1, le=200)`` on ``limit`` /
  ``Field(ge=0)`` on ``offset`` and ``total``) so a Pydantic
  ``ValidationError`` fires before the router code runs. Router
  code never duplicates these guards. The ``limit`` bound mirrors
  PR #10 staging (``ge=1, le=200``) for cross-endpoint consistency.

- **Plan D13 — OpenAPI examples mandatory.** Each DTO carries a
  happy-path example via ``model_config.json_schema_extra``. Router
  modules (Group B+) add the 429 / 422 / empty-list examples at the
  response layer because those live in the router's
  ``responses=`` dict.

Plan D10 forbids widening ``CurrentUser`` shape. No auth DTOs live
here — ``/auth/me`` keeps the PR #2 DTO in ``api.auth.schemas``.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# List items
# ---------------------------------------------------------------------------


class ReportItem(BaseModel):
    """Single report row in the ``/reports`` list view.

    Minimal fields only — detail endpoints are plan D9 deferred to
    Phase 3 (``/reports/{id}`` + ``/reports/{id}/similar`` land
    together). ``tlp`` ships now so the FE does not need a schema
    migration when AMBER filtering arrives (plan D4).
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 42,
                    "title": "Lazarus targets South Korean crypto exchanges",
                    "url": "https://mandiant.com/blog/lazarus-2026q1",
                    "url_canonical": "https://mandiant.com/blog/lazarus-2026q1",
                    "published": "2026-03-15",
                    "source_id": 7,
                    "source_name": "Mandiant",
                    "lang": "en",
                    "tlp": "WHITE",
                }
            ]
        },
    )

    id: int
    title: str
    url: str
    url_canonical: str
    published: date
    source_id: int | None = None
    source_name: str | None = None
    lang: str | None = None
    tlp: str | None = None


class IncidentItem(BaseModel):
    """Single incident row in the ``/incidents`` list view.

    ``motivations`` / ``sectors`` / ``countries`` are flattened from
    the three N:M join tables (``incident_motivations`` /
    ``incident_sectors`` / ``incident_countries``) — the aggregator
    in Group D does the grouping so the client sees a flat list per
    row instead of three round-trips.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 18,
                    "reported": "2024-05-02",
                    "title": "Axie Infinity Ronin bridge exploit",
                    "description": "620M USD bridge compromise attributed to Lazarus",
                    "est_loss_usd": 620000000,
                    "attribution_confidence": "HIGH",
                    "motivations": ["financial"],
                    "sectors": ["crypto"],
                    "countries": ["VN", "SG"],
                }
            ]
        },
    )

    id: int
    reported: date | None = None
    title: str
    description: str | None = None
    est_loss_usd: int | None = None
    attribution_confidence: str | None = None
    motivations: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)


class ActorItem(BaseModel):
    """Single actor row in the ``/actors`` list view.

    ``codenames`` flattens the ``codenames`` table join on
    ``group_id``. Fields mirror the v1.0 §5.4 shape verbatim so the
    FE consumer lands without a rename pass.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 3,
                    "name": "Lazarus Group",
                    "mitre_intrusion_set_id": "G0032",
                    "aka": ["APT38", "Hidden Cobra"],
                    "description": "DPRK-attributed cyber espionage and financially motivated group",
                    "codenames": ["Andariel", "Bluenoroff"],
                }
            ]
        },
    )

    id: int
    name: str
    mitre_intrusion_set_id: str | None = None
    aka: list[str] = Field(default_factory=list)
    description: str | None = None
    codenames: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# List envelopes — keyset (reports/incidents) vs offset (actors)
# ---------------------------------------------------------------------------


class ReportListResponse(BaseModel):
    """Keyset-paginated response for ``GET /api/v1/reports``.

    ``next_cursor`` is ``None`` on the final page. The cursor is
    opaque — see ``api.read.pagination``.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "id": 42,
                            "title": "Lazarus targets South Korean crypto exchanges",
                            "url": "https://mandiant.com/blog/lazarus-2026q1",
                            "url_canonical": "https://mandiant.com/blog/lazarus-2026q1",
                            "published": "2026-03-15",
                            "source_id": 7,
                            "source_name": "Mandiant",
                            "lang": "en",
                            "tlp": "WHITE",
                        }
                    ],
                    "next_cursor": "MjAyNi0wMy0xNXw0Mg",
                },
                {"items": [], "next_cursor": None},
            ]
        },
    )

    items: list[ReportItem]
    next_cursor: str | None = None


class IncidentListResponse(BaseModel):
    """Keyset-paginated response for ``GET /api/v1/incidents``."""

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "id": 18,
                            "reported": "2024-05-02",
                            "title": "Axie Infinity Ronin bridge exploit",
                            "description": "620M USD bridge compromise attributed to Lazarus",
                            "est_loss_usd": 620000000,
                            "attribution_confidence": "HIGH",
                            "motivations": ["financial"],
                            "sectors": ["crypto"],
                            "countries": ["VN", "SG"],
                        }
                    ],
                    "next_cursor": "MjAyNC0wNS0wMnwxOA",
                },
                {"items": [], "next_cursor": None},
            ]
        },
    )

    items: list[IncidentItem]
    next_cursor: str | None = None


class ActorListResponse(BaseModel):
    """Offset-paginated response for ``GET /api/v1/actors``.

    Plan D3 lock: actors stay on offset because the group count is
    small and sort-stable under inserts (``name ASC, id ASC`` per
    D11). ``total`` lets the FE compute remaining pages without a
    second ``HEAD``-style call.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "id": 3,
                            "name": "Lazarus Group",
                            "mitre_intrusion_set_id": "G0032",
                            "aka": ["APT38", "Hidden Cobra"],
                            "description": "DPRK-attributed cyber espionage and financially motivated group",
                            "codenames": ["Andariel", "Bluenoroff"],
                        }
                    ],
                    "limit": 50,
                    "offset": 0,
                    "total": 12,
                },
                {"items": [], "limit": 50, "offset": 0, "total": 0},
            ]
        },
    )

    items: list[ActorItem]
    limit: Annotated[int, Field(ge=1, le=200)]
    offset: Annotated[int, Field(ge=0)]
    total: Annotated[int, Field(ge=0)]


# ---------------------------------------------------------------------------
# Dashboard summary (plan D6)
# ---------------------------------------------------------------------------


class DashboardYearCount(BaseModel):
    """One point in ``DashboardSummary.reports_by_year``."""

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={"examples": [{"year": 2024, "count": 38}]},
    )

    year: Annotated[int, Field(ge=1900, le=2100)]
    count: Annotated[int, Field(ge=0)]


class DashboardMotivationCount(BaseModel):
    """One point in ``DashboardSummary.incidents_by_motivation``."""

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={"examples": [{"motivation": "financial", "count": 27}]},
    )

    motivation: str
    count: Annotated[int, Field(ge=0)]


class DashboardTopGroup(BaseModel):
    """One entry in ``DashboardSummary.top_groups`` (length bounded by
    the ``top_n`` query param — min 1, max 20, default 5)."""

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [{"group_id": 3, "name": "Lazarus Group", "report_count": 104}]
        },
    )

    group_id: int
    name: str
    report_count: Annotated[int, Field(ge=0)]


class DashboardSummary(BaseModel):
    """Response for ``GET /api/v1/dashboard/summary``.

    Plan D6 lock: three scalar totals + three aggregate arrays. The
    shape is the minimum an FE KPI card view (§14 Phase 2 W1–W2)
    needs — no nesting beyond one level, no per-day series (that
    lives on the analytics endpoints in Phase 3).
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "total_reports": 1204,
                    "total_incidents": 154,
                    "total_actors": 12,
                    "reports_by_year": [
                        {"year": 2022, "count": 201},
                        {"year": 2023, "count": 287},
                        {"year": 2024, "count": 318},
                    ],
                    "incidents_by_motivation": [
                        {"motivation": "financial", "count": 81},
                        {"motivation": "espionage", "count": 52},
                        {"motivation": "disruption", "count": 21},
                    ],
                    "top_groups": [
                        {"group_id": 3, "name": "Lazarus Group", "report_count": 412},
                        {"group_id": 5, "name": "Kimsuky", "report_count": 287},
                    ],
                }
            ]
        },
    )

    total_reports: Annotated[int, Field(ge=0)]
    total_incidents: Annotated[int, Field(ge=0)]
    total_actors: Annotated[int, Field(ge=0)]
    reports_by_year: list[DashboardYearCount] = Field(default_factory=list)
    incidents_by_motivation: list[DashboardMotivationCount] = Field(default_factory=list)
    top_groups: list[DashboardTopGroup] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Analytics — PR #13 Phase 2.4 plan D2
# ---------------------------------------------------------------------------
#
# Three read-only endpoints feed the dashboard visualizations layer:
#
#     GET /api/v1/analytics/attack_matrix  → AttackMatrixResponse
#     GET /api/v1/analytics/trend          → TrendResponse
#     GET /api/v1/analytics/geo            → GeoResponse
#
# Plan D2 locks the wire shape. The three DTOs all share the same
# ``date_from`` / ``date_to`` / ``group_id[]`` query contract as
# ``/dashboard/summary``; see the aggregator module for filter-scope
# details (notably that ``group_id[]`` is a no-op for the geo response
# because the schema does not connect incidents to groups).
#
# Response-shape invariants enforced at the DTO layer:
#
# - ``attack_matrix`` is row-based by tactic. Techniques with null
#   ``techniques.tactic`` are dropped by the aggregator so every row
#   here has a non-empty ``tactic_id``.
# - ``trend`` uses strict ``YYYY-MM`` month bucketing (date-only column
#   upstream, so no UTC-vs-local ambiguity). Zero-count months are
#   omitted rather than zero-filled — the FE decides on gap-fill.
# - ``geo`` uses ISO 3166-1 alpha-2 country codes. No DPRK special-case
#   field: ``KP`` is a plain country row when present; the FE handles
#   highlight per plan D7.


class TacticRef(BaseModel):
    """MITRE ATT&CK tactic identifier.

    ``id`` is the raw ``techniques.tactic`` string (e.g. ``"TA0001"``,
    ``"initial-access"``, or a human form — the column is free-form in
    migration 0001). ``name`` mirrors it; callers that want a canonical
    label do the lookup client-side.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={"examples": [{"id": "TA0001", "name": "TA0001"}]},
    )

    id: str
    name: str


class AttackTechniqueCount(BaseModel):
    """One technique entry inside a tactic row.

    ``technique_id`` is the MITRE public id (``techniques.mitre_id``,
    e.g. ``"T1566"``), not the internal DB id, so the FE does not
    need the DB table to resolve a display label.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={"examples": [{"technique_id": "T1566", "count": 18}]},
    )

    technique_id: str
    count: Annotated[int, Field(ge=0)]


class AttackTacticRow(BaseModel):
    """Group of technique counts under a single tactic."""

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "tactic_id": "TA0001",
                    "techniques": [
                        {"technique_id": "T1566", "count": 18},
                        {"technique_id": "T1190", "count": 7},
                    ],
                }
            ]
        },
    )

    tactic_id: str
    techniques: list[AttackTechniqueCount] = Field(default_factory=list)


class AttackMatrixResponse(BaseModel):
    """Response for ``GET /api/v1/analytics/attack_matrix``.

    Row-based shape (plan D2 lock). ``tactics`` is the distinct set of
    tactics appearing in ``rows`` — FE uses it for axis / legend
    ordering without re-scanning rows. ``rows`` is sorted by total
    technique count per tactic (desc) then by ``tactic_id`` asc for
    stable tie-breaking; within a row, techniques are sorted by count
    desc then ``technique_id`` asc.

    The default query-side ``top_n`` bound (30, max 200) is enforced at
    the router layer; the DTO only guarantees that every
    ``AttackTechniqueCount`` row has ``count >= 0`` (never a negative
    inflation artifact).
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "tactics": [
                        {"id": "TA0001", "name": "TA0001"},
                        {"id": "TA0002", "name": "TA0002"},
                    ],
                    "rows": [
                        {
                            "tactic_id": "TA0001",
                            "techniques": [
                                {"technique_id": "T1566", "count": 18},
                                {"technique_id": "T1190", "count": 7},
                            ],
                        },
                        {
                            "tactic_id": "TA0002",
                            "techniques": [
                                {"technique_id": "T1059", "count": 12},
                            ],
                        },
                    ],
                },
                {"tactics": [], "rows": []},
            ]
        },
    )

    tactics: list[TacticRef] = Field(default_factory=list)
    rows: list[AttackTacticRow] = Field(default_factory=list)


class TrendBucket(BaseModel):
    """One monthly bucket in ``TrendResponse.buckets``.

    ``month`` is strict ``YYYY-MM`` (zero-padded). The upstream column
    (``reports.published``) is a date, not a timestamp, so there is no
    UTC-vs-local ambiguity — the bucket is the calendar month of the
    date stored.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={"examples": [{"month": "2026-03", "count": 47}]},
    )

    month: Annotated[str, Field(pattern=r"^\d{4}-\d{2}$")]
    count: Annotated[int, Field(ge=0)]


class TrendResponse(BaseModel):
    """Response for ``GET /api/v1/analytics/trend``.

    Report-volume time series grouped by calendar month of
    ``reports.published``. Plan D2 lock. ``count`` is distinct report
    count per bucket. ``buckets`` is sorted by ``month`` ascending.

    Zero-count months are **omitted**, not zero-filled. The FE chooses
    whether to fill gaps for its chart axis — the BE has no opinion on
    the visualization cadence.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "buckets": [
                        {"month": "2026-01", "count": 41},
                        {"month": "2026-02", "count": 38},
                        {"month": "2026-03", "count": 47},
                    ],
                },
                {"buckets": []},
            ]
        },
    )

    buckets: list[TrendBucket] = Field(default_factory=list)


class GeoCountry(BaseModel):
    """One country aggregate in ``GeoResponse.countries``."""

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={"examples": [{"iso2": "KP", "count": 9}]},
    )

    iso2: Annotated[str, Field(min_length=2, max_length=2)]
    count: Annotated[int, Field(ge=0)]


class GeoResponse(BaseModel):
    """Response for ``GET /api/v1/analytics/geo``.

    Country-aggregated incident counts. Plan D2 lock: no DPRK special-
    case field — ``KP`` is a plain row when present; plan D7 says the
    FE owns the highlight. ``countries`` is sorted by ``count`` desc
    then ``iso2`` asc for stable tie-breaking.

    Scope caveat (same as ``incidents_by_motivation`` on the dashboard
    summary): the ``group_id[]`` filter is a no-op for this response
    because the schema has no path from ``incidents`` to ``groups``.
    Date filter (``incidents.reported``) does apply.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "countries": [
                        {"iso2": "KR", "count": 18},
                        {"iso2": "US", "count": 9},
                        {"iso2": "KP", "count": 2},
                    ]
                },
                {"countries": []},
            ]
        },
    )

    countries: list[GeoCountry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Detail views — PR #14 Phase 3 slice 1 (plan D1 + D9 + D11)
# ---------------------------------------------------------------------------
#
# Three read-only detail endpoints feed the detail pages:
#
#     GET /api/v1/reports/{id}    → ReportDetail
#     GET /api/v1/incidents/{id}  → IncidentDetail
#     GET /api/v1/actors/{id}     → ActorDetail
#
# Design contract locked in ``docs/plans/pr14-detail-views.md``:
#
# - **D9 Payload depth** — shallow joins only, heavy collections
#   capped, no recursive nesting. Cap enforcement is **dual-layer**:
#   the aggregator applies LIMIT in SQL so the DB never materializes
#   more rows than necessary, AND this DTO declares the same ceiling
#   via ``Field(max_length=...)`` so a bypass that forgot the LIMIT
#   would fail validation. The SQL-layer cap is the performance guard;
#   the DTO-layer cap is the contract guard.
#
# - **D11 Navigation contract** — report ↔ incident linking runs
#   through ``incident_sources`` (migration 0001 M:N table). Linked
#   entries in either direction are ``{id, title, ...}`` summaries,
#   not full list-item DTOs — the page renders a link, not a second
#   full panel. ``ActorDetail`` deliberately does NOT carry linked
#   reports (that needs ``report_codenames`` — out of scope this PR).
#
# - **D10 Missing similarity fallback** — irrelevant to the 3 detail
#   endpoints here; D10 applies only to ``/reports/{id}/similar``
#   (Group B).

# Cap constants — plan D9. Module-level so tests can reference the
# same ceiling the DTOs + aggregator use; a single-source lock means
# any future bump lands in exactly one place.
REPORT_DETAIL_INCIDENTS_CAP = 10
INCIDENT_DETAIL_REPORTS_CAP = 20


class LinkedIncidentSummary(BaseModel):
    """One row in ``ReportDetail.linked_incidents`` (plan D9 + D11).

    Shallow summary only — ``{id, title, reported}``. A click
    navigates to ``/incidents/{id}`` for the full detail. No nested
    motivations / sectors / countries arrays here (that would
    recursively expand per D9's "no recursive nesting" rule).
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 18,
                    "title": "Axie Infinity Ronin bridge exploit",
                    "reported": "2024-05-02",
                }
            ]
        },
    )

    id: int
    title: str
    reported: date | None = None


class LinkedReportSummary(BaseModel):
    """One row in ``IncidentDetail.linked_reports`` (plan D9 + D11).

    Shallow summary only — ``{id, title, url, published, source_name}``.
    A click navigates to ``/reports/{id}`` for the full detail.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 42,
                    "title": "Lazarus targets SK crypto exchanges",
                    "url": "https://mandiant.com/blog/lazarus-2026q1",
                    "published": "2026-03-15",
                    "source_name": "Mandiant",
                }
            ]
        },
    )

    id: int
    title: str
    url: str
    published: date
    source_name: str | None = None


class ReportDetail(BaseModel):
    """Response for ``GET /api/v1/reports/{id}`` (plan D1 + D9 + D11).

    All core ``ReportItem`` fields plus the free-form fields kept off
    the list view (``summary``, ``reliability``, ``credibility``) plus
    flat tag / codename / technique id lists (each bounded by schema,
    no additional cap needed) plus the capped ``linked_incidents``
    list (per D9 cap ``REPORT_DETAIL_INCIDENTS_CAP``; ordered by
    ``incidents.reported DESC, id DESC`` to surface the newest
    incidents first when the full set exceeds the cap).

    D10 forbids fake or heuristic fallbacks on the similarity
    endpoint — this detail endpoint has no similarity surface, but
    the same honesty rule applies: linked_incidents reflects the
    actual ``incident_sources`` join, never a heuristic substitute.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 42,
                    "title": "Lazarus targets South Korean crypto exchanges",
                    "url": "https://mandiant.com/blog/lazarus-2026q1",
                    "url_canonical": "https://mandiant.com/blog/lazarus-2026q1",
                    "published": "2026-03-15",
                    "source_id": 7,
                    "source_name": "Mandiant",
                    "lang": "en",
                    "tlp": "WHITE",
                    "summary": "Operation targeting crypto exchanges in Q1 2026.",
                    "reliability": "A",
                    "credibility": "2",
                    "tags": ["ransomware", "finance"],
                    "codenames": ["Andariel"],
                    "techniques": ["T1566", "T1190"],
                    "linked_incidents": [
                        {
                            "id": 18,
                            "title": "Axie Infinity Ronin bridge exploit",
                            "reported": "2024-05-02",
                        }
                    ],
                },
                {
                    "id": 7,
                    "title": "Single report without incident link",
                    "url": "https://example.test/r/7",
                    "url_canonical": "https://example.test/r/7",
                    "published": "2026-01-10",
                    "source_id": None,
                    "source_name": None,
                    "lang": "en",
                    "tlp": "WHITE",
                    "summary": None,
                    "reliability": None,
                    "credibility": None,
                    "tags": [],
                    "codenames": [],
                    "techniques": [],
                    "linked_incidents": [],
                },
            ]
        },
    )

    id: int
    title: str
    url: str
    url_canonical: str
    published: date
    source_id: int | None = None
    source_name: str | None = None
    lang: str | None = None
    tlp: str | None = None
    summary: str | None = None
    reliability: str | None = None
    credibility: str | None = None
    tags: list[str] = Field(default_factory=list)
    codenames: list[str] = Field(default_factory=list)
    techniques: list[str] = Field(default_factory=list)
    # max_length mirrors REPORT_DETAIL_INCIDENTS_CAP. Pydantic
    # validates at construction time; a bypass path that skipped the
    # aggregator's LIMIT would surface as ValidationError here.
    linked_incidents: Annotated[
        list[LinkedIncidentSummary],
        Field(default_factory=list, max_length=REPORT_DETAIL_INCIDENTS_CAP),
    ]


class IncidentDetail(BaseModel):
    """Response for ``GET /api/v1/incidents/{id}`` (plan D1 + D9 + D11).

    All core ``IncidentItem`` fields (including flat motivations /
    sectors / countries arrays) plus the capped ``linked_reports``
    list (per D9 cap ``INCIDENT_DETAIL_REPORTS_CAP``; ordered by
    ``reports.published DESC, reports.id DESC`` to surface the newest
    reports first when the full set exceeds the cap).
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 18,
                    "reported": "2024-05-02",
                    "title": "Axie Infinity Ronin bridge exploit",
                    "description": "620M USD bridge compromise attributed to Lazarus",
                    "est_loss_usd": 620000000,
                    "attribution_confidence": "HIGH",
                    "motivations": ["financial"],
                    "sectors": ["crypto"],
                    "countries": ["VN", "SG"],
                    "linked_reports": [
                        {
                            "id": 42,
                            "title": "Lazarus targets SK crypto exchanges",
                            "url": "https://mandiant.com/blog/lazarus-2026q1",
                            "published": "2026-03-15",
                            "source_name": "Mandiant",
                        }
                    ],
                },
                {
                    "id": 99,
                    "reported": None,
                    "title": "Incident without source reports yet",
                    "description": None,
                    "est_loss_usd": None,
                    "attribution_confidence": None,
                    "motivations": [],
                    "sectors": [],
                    "countries": [],
                    "linked_reports": [],
                },
            ]
        },
    )

    id: int
    reported: date | None = None
    title: str
    description: str | None = None
    est_loss_usd: int | None = None
    attribution_confidence: str | None = None
    motivations: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    linked_reports: Annotated[
        list[LinkedReportSummary],
        Field(default_factory=list, max_length=INCIDENT_DETAIL_REPORTS_CAP),
    ]


# ---------------------------------------------------------------------------
# Similar reports — PR #14 Phase 3 slice 1 Group B (plan D2 + D8 + D10)
# ---------------------------------------------------------------------------
#
# ``GET /api/v1/reports/{id}/similar?k=10`` returns a pgvector kNN
# result against ``reports.embedding`` (migration 0001 line 97).
#
# D8 locked semantics:
#   - Self-exclusion: the source report is never in the result set.
#   - Stable sort: ``score DESC, report_id ASC`` tie-breaker so the
#     same input produces the same ordering across runs (Pact relies
#     on this).
#   - k bounds: ``k ∈ [1, 50]``, default 10. Enforced at the router's
#     ``Query(ge=SIMILAR_K_MIN, le=SIMILAR_K_MAX)``.
#   - Cache key includes both ``report_id`` AND ``k`` (separate slots
#     don't pollute each other).
#
# D10 locked empty contract (critical):
#   - Source report has NULL embedding → ``200`` + ``{items: []}``.
#   - kNN returns zero rows after self-exclusion → ``200`` + ``{items: []}``.
#   - ``500`` is forbidden on this endpoint.
#   - No fake / heuristic fallback (no "recent N" stand-in, no
#     "shared-tag overlap"). Empty is the honest signal.

SIMILAR_K_MIN = 1
SIMILAR_K_MAX = 50
SIMILAR_K_DEFAULT = 10


# PR #15 plan D2 — /actors/{id}/reports keyset-paginated list. Limits
# mirror /reports (PR #11 D3) so the two endpoints share one rate-of-
# ingest ceiling. Default 50 matches the other list endpoints.
ACTOR_REPORTS_LIMIT_MIN = 1
ACTOR_REPORTS_LIMIT_MAX = 200
ACTOR_REPORTS_LIMIT_DEFAULT = 50


# PR #17 plan D13 — /search FTS-only MVP. Default 10 matches /similar;
# max 50 caps the palette "show more" room without widening pagination.
# ``vector_rank`` is a forward-compat slot (D9) filled by the follow-up
# hybrid PR; this slice always emits ``null``.
SEARCH_LIMIT_MIN = 1
SEARCH_LIMIT_MAX = 50
SEARCH_LIMIT_DEFAULT = 10
SEARCH_CACHE_TTL_SECONDS = 60


class SimilarReportEntry(BaseModel):
    """One row in ``SimilarReportsResponse.items`` (plan D8).

    ``report`` is the shallow ``LinkedReportSummary`` used elsewhere
    in PR #14 — same shape as the incident detail's linked reports
    list so the FE can render both panels with one row component.
    ``score`` is cosine similarity in ``[0, 1]`` (pgvector's
    ``<=>`` is cosine DISTANCE; we emit ``1 - distance`` so higher
    values mean "more similar" — matches the analyst mental model).
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "report": {
                        "id": 99,
                        "title": "Related Lazarus campaign",
                        "url": "https://mandiant.com/blog/lazarus-2025q4",
                        "published": "2025-12-01",
                        "source_name": "Mandiant",
                    },
                    "score": 0.87,
                }
            ]
        },
    )

    report: LinkedReportSummary
    score: Annotated[float, Field(ge=0.0, le=1.0)]


class SimilarReportsResponse(BaseModel):
    """Response for ``GET /api/v1/reports/{id}/similar`` (plan D2 + D8 + D10).

    Length bounded by ``k`` (the router enforces ``k ∈ [1, 50]``);
    this DTO uses ``max_length=SIMILAR_K_MAX`` as the DTO-layer
    guard so a bypass that fetched more than the cap would surface
    as ValidationError rather than silently oversizing the response.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "report": {
                                "id": 99,
                                "title": "Related Lazarus campaign",
                                "url": "https://mandiant.com/blog/lazarus-2025q4",
                                "published": "2025-12-01",
                                "source_name": "Mandiant",
                            },
                            "score": 0.87,
                        }
                    ]
                },
                # Plan D10 empty contract — no fake similarity
                # fallback. Source has no embedding OR kNN returned
                # zero rows after self-exclusion: both paths emit
                # ``{items: []}`` with 200 OK.
                {"items": []},
            ]
        },
    )

    items: Annotated[
        list[SimilarReportEntry],
        Field(default_factory=list, max_length=SIMILAR_K_MAX),
    ]


# ---------------------------------------------------------------------------
# PR #17 /search FTS-only MVP (plan D9 / D10 / D12)
# ---------------------------------------------------------------------------
#
# Hybrid (BM25 + vector + RRF) is the Draft v1 design target but was
# blocked at plan lock by OI5 = B: llm-proxy has no embedding endpoint
# today. This slice ships the FTS half only; the ``vector_rank`` slot
# on every SearchHit is reserved as ``None`` so the follow-up hybrid
# PR can fill it without breaking the JSON schema (additive change).


class SearchHit(BaseModel):
    """One row in ``SearchResponse.items`` (plan D9).

    FTS-only MVP shape:
        - ``report``: the full ReportItem (id, title, url, url_canonical,
          published, source_id, source_name, lang, tlp) — same DTO the
          /reports list returns, so FE row components are reusable.
        - ``fts_rank``: PostgreSQL ``ts_rank_cd`` value (positive float;
          higher = better match). Non-negative by construction since
          ``ts_rank_cd`` over a `simple` tsvector always returns >= 0.
        - ``vector_rank``: **always ``None`` this slice** (D9 forward-
          compat slot). The follow-up hybrid PR will fill this with the
          1-indexed rank position within the vector-kNN result list.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "report": {
                        "id": 999060,
                        "title": "Lazarus targets SK crypto exchanges",
                        "url": "https://pact.test/search/lazarus-1",
                        "url_canonical": "https://pact.test/search/lazarus-1",
                        "published": "2026-03-15",
                        "source_id": 1,
                        "source_name": "Vendor",
                        "lang": "en",
                        "tlp": "WHITE",
                    },
                    "fts_rank": 0.0759,
                    "vector_rank": None,
                }
            ]
        },
    )

    report: ReportItem
    fts_rank: Annotated[float, Field(ge=0.0)]
    # Literal None this slice. Keep Optional[int] so the follow-up
    # hybrid PR fills it without schema churn (FE Zod already accepts
    # `z.number().int().nullable()` for the same reason).
    vector_rank: int | None = None


class SearchResponse(BaseModel):
    """Response for ``GET /api/v1/search`` (plan D9 / D10 / D12).

    Envelope:
        - ``items``: up to ``SEARCH_LIMIT_MAX`` hits ordered by FTS
          rank DESC, tiebroken by ``reports.id DESC`` (D2 locks the
          stable secondary key).
        - ``total_hits``: count of rows matched by the FTS predicate
          BEFORE the ``LIMIT`` is applied (not the per-page count).
          Hard-capped at a sane ceiling by the service layer so a
          pathological query doesn't scan the corpus twice.
        - ``latency_ms``: envelope-level observability of the
          per-request server-side time. Sub-budgets (fts_ms,
          cache_hit) are logged via D16 — not echoed in the payload.

    D10 empty contract: zero-match queries emit
    ``{items: [], total_hits: 0, latency_ms: <int>}`` with 200 OK.
    NOT 404, NOT 500, NO fake fallback.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "report": {
                                "id": 999060,
                                "title": "Lazarus targets SK crypto exchanges",
                                "url": "https://pact.test/search/lazarus-1",
                                "url_canonical": "https://pact.test/search/lazarus-1",
                                "published": "2026-03-15",
                                "source_id": 1,
                                "source_name": "Vendor",
                                "lang": "en",
                                "tlp": "WHITE",
                            },
                            "fts_rank": 0.0759,
                            "vector_rank": None,
                        }
                    ],
                    "total_hits": 1,
                    "latency_ms": 42,
                },
                # Plan D10 empty contract — zero FTS matches.
                {"items": [], "total_hits": 0, "latency_ms": 12},
            ]
        },
    )

    items: Annotated[
        list[SearchHit],
        Field(default_factory=list, max_length=SEARCH_LIMIT_MAX),
    ]
    total_hits: Annotated[int, Field(ge=0)]
    latency_ms: Annotated[int, Field(ge=0)]


class ActorDetail(BaseModel):
    """Response for ``GET /api/v1/actors/{id}`` (plan D1 + D11).

    All core ``ActorItem`` fields plus no linked-reports collection:
    per plan D11 out-of-scope ruling, ``ActorDetail`` does NOT
    traverse ``report_codenames`` to surface reports that mention
    this actor. That surface needs a dedicated endpoint whose filter
    contract, pagination, and RBAC scope have not been locked yet —
    carried to a later Phase 3 slice. The FE consequence: there is
    no "recent reports for this actor" panel on the actor detail
    page this PR.
    """

    model_config = ConfigDict(
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 3,
                    "name": "Lazarus Group",
                    "mitre_intrusion_set_id": "G0032",
                    "aka": ["APT38", "Hidden Cobra"],
                    "description": "DPRK-attributed cyber espionage and financially motivated group",
                    "codenames": ["Andariel", "Bluenoroff"],
                }
            ]
        },
    )

    id: int
    name: str
    mitre_intrusion_set_id: str | None = None
    aka: list[str] = Field(default_factory=list)
    description: str | None = None
    codenames: list[str] = Field(default_factory=list)


__all__ = [
    "ACTOR_REPORTS_LIMIT_DEFAULT",
    "ACTOR_REPORTS_LIMIT_MAX",
    "ACTOR_REPORTS_LIMIT_MIN",
    "SEARCH_CACHE_TTL_SECONDS",
    "SEARCH_LIMIT_DEFAULT",
    "SEARCH_LIMIT_MAX",
    "SEARCH_LIMIT_MIN",
    "ActorDetail",
    "ActorItem",
    "ActorListResponse",
    "AttackMatrixResponse",
    "AttackTacticRow",
    "AttackTechniqueCount",
    "DashboardMotivationCount",
    "DashboardSummary",
    "DashboardTopGroup",
    "DashboardYearCount",
    "GeoCountry",
    "GeoResponse",
    "INCIDENT_DETAIL_REPORTS_CAP",
    "IncidentDetail",
    "IncidentItem",
    "IncidentListResponse",
    "LinkedIncidentSummary",
    "LinkedReportSummary",
    "REPORT_DETAIL_INCIDENTS_CAP",
    "ReportDetail",
    "ReportItem",
    "ReportListResponse",
    "SIMILAR_K_DEFAULT",
    "SIMILAR_K_MAX",
    "SIMILAR_K_MIN",
    "SearchHit",
    "SearchResponse",
    "SimilarReportEntry",
    "SimilarReportsResponse",
    "TacticRef",
    "TrendBucket",
    "TrendResponse",
]

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


__all__ = [
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
    "IncidentItem",
    "IncidentListResponse",
    "ReportItem",
    "ReportListResponse",
    "TacticRef",
    "TrendBucket",
    "TrendResponse",
]

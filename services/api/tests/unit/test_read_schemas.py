"""Unit tests for ``api.schemas.read`` — read surface DTOs.

Scope from plan §2.1 D3 / D6 / D11 / D12 / D13 and Group A review
priorities (cursor opaque; envelope separation; no /auth/me
pollution; 422-uniform invalid inputs; examples baked in).

These tests intentionally do not touch SQL / routers — the goal is
DTO-layer enforcement is strong enough that Group B–E routers can
stop worrying about shape validation and focus on query composition.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from api.schemas.read import (
    ActorItem,
    ActorListResponse,
    DashboardMotivationCount,
    DashboardSummary,
    DashboardTopGroup,
    DashboardYearCount,
    IncidentItem,
    IncidentListResponse,
    ReportItem,
    ReportListResponse,
)


# ---------------------------------------------------------------------------
# ReportItem — happy + optional-field handling
# ---------------------------------------------------------------------------


class TestReportItem:
    def test_full_payload(self) -> None:
        item = ReportItem(
            id=42,
            title="example",
            url="https://ex.com/r",
            url_canonical="https://ex.com/r",
            published=date(2026, 3, 15),
            source_id=7,
            source_name="Mandiant",
            lang="en",
            tlp="WHITE",
        )
        assert item.id == 42
        assert item.tlp == "WHITE"

    def test_minimal_required(self) -> None:
        """Only the non-nullable columns from ``reports`` are required."""
        item = ReportItem(
            id=1,
            title="t",
            url="https://x/",
            url_canonical="https://x/",
            published=date(2026, 1, 1),
        )
        assert item.source_id is None
        assert item.tlp is None

    def test_frozen(self) -> None:
        item = ReportItem(
            id=1,
            title="t",
            url="https://x/",
            url_canonical="https://x/",
            published=date(2026, 1, 1),
        )
        with pytest.raises(ValidationError):
            item.id = 2  # type: ignore[misc]

    def test_missing_required_raises(self) -> None:
        with pytest.raises(ValidationError):
            ReportItem.model_validate(
                {
                    "id": 1,
                    "title": "t",
                    # url missing
                    "url_canonical": "https://x/",
                    "published": "2026-01-01",
                }
            )


# ---------------------------------------------------------------------------
# IncidentItem — list defaults, optional reported
# ---------------------------------------------------------------------------


class TestIncidentItem:
    def test_full_payload(self) -> None:
        item = IncidentItem(
            id=18,
            reported=date(2024, 5, 2),
            title="Axie Ronin bridge exploit",
            description="620M USD",
            est_loss_usd=620_000_000,
            attribution_confidence="HIGH",
            motivations=["financial"],
            sectors=["crypto"],
            countries=["VN", "SG"],
        )
        assert item.motivations == ["financial"]
        assert item.countries == ["VN", "SG"]

    def test_reported_nullable(self) -> None:
        """``incidents.reported`` is nullable in the schema."""
        item = IncidentItem(id=1, title="no date", reported=None)
        assert item.reported is None

    def test_default_lists_are_empty(self) -> None:
        item = IncidentItem(id=1, title="bare")
        assert item.motivations == []
        assert item.sectors == []
        assert item.countries == []


# ---------------------------------------------------------------------------
# ActorItem
# ---------------------------------------------------------------------------


class TestActorItem:
    def test_full_payload(self) -> None:
        item = ActorItem(
            id=3,
            name="Lazarus Group",
            mitre_intrusion_set_id="G0032",
            aka=["APT38"],
            description="DPRK-attributed",
            codenames=["Andariel"],
        )
        assert item.name == "Lazarus Group"
        assert item.aka == ["APT38"]

    def test_defaults(self) -> None:
        item = ActorItem(id=1, name="X")
        assert item.aka == []
        assert item.codenames == []
        assert item.mitre_intrusion_set_id is None


# ---------------------------------------------------------------------------
# Keyset envelopes — reports + incidents
# ---------------------------------------------------------------------------


class TestKeysetEnvelopes:
    def test_report_list_accepts_opaque_cursor_str(self) -> None:
        resp = ReportListResponse(items=[], next_cursor="MjAyNi0wMy0xNXw0Mg")
        assert resp.next_cursor == "MjAyNi0wMy0xNXw0Mg"

    def test_report_list_next_cursor_nullable(self) -> None:
        resp = ReportListResponse(items=[], next_cursor=None)
        assert resp.next_cursor is None

    def test_incident_list_accepts_opaque_cursor_str(self) -> None:
        resp = IncidentListResponse(items=[], next_cursor="abc")
        assert resp.next_cursor == "abc"

    def test_envelopes_are_distinct_classes(self) -> None:
        """Plan §2.1 D3 / review priority: keyset envelopes must not
        share a base class that silently bleeds into actors. Assert
        the two keyset types are genuinely independent class objects
        (not a type alias)."""
        assert ReportListResponse is not IncidentListResponse


# ---------------------------------------------------------------------------
# Offset envelope — actors only
# ---------------------------------------------------------------------------


class TestActorListResponse:
    def test_full_payload(self) -> None:
        resp = ActorListResponse(items=[], limit=50, offset=0, total=12)
        assert resp.limit == 50
        assert resp.total == 12

    def test_limit_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            ActorListResponse(items=[], limit=0, offset=0, total=0)
        with pytest.raises(ValidationError):
            ActorListResponse(items=[], limit=201, offset=0, total=0)

    def test_negative_offset_raises(self) -> None:
        with pytest.raises(ValidationError):
            ActorListResponse(items=[], limit=50, offset=-1, total=0)

    def test_negative_total_raises(self) -> None:
        with pytest.raises(ValidationError):
            ActorListResponse(items=[], limit=50, offset=0, total=-1)

    def test_has_no_next_cursor_attribute(self) -> None:
        """Actors envelope must NOT grow a ``next_cursor`` — plan D3
        keeps actors on offset pagination deliberately. If this
        fails, a future edit accidentally unified envelopes."""
        resp = ActorListResponse(items=[], limit=50, offset=0, total=0)
        assert not hasattr(resp, "next_cursor")


# ---------------------------------------------------------------------------
# Dashboard DTOs
# ---------------------------------------------------------------------------


class TestDashboardDTOs:
    def test_year_count_bounds(self) -> None:
        DashboardYearCount(year=2024, count=0)
        DashboardYearCount(year=1900, count=100)
        DashboardYearCount(year=2100, count=100)
        with pytest.raises(ValidationError):
            DashboardYearCount(year=1899, count=0)
        with pytest.raises(ValidationError):
            DashboardYearCount(year=2101, count=0)
        with pytest.raises(ValidationError):
            DashboardYearCount(year=2024, count=-1)

    def test_motivation_count_rejects_negative(self) -> None:
        with pytest.raises(ValidationError):
            DashboardMotivationCount(motivation="financial", count=-1)

    def test_top_group_rejects_negative_report_count(self) -> None:
        with pytest.raises(ValidationError):
            DashboardTopGroup(group_id=1, name="X", report_count=-1)

    def test_summary_full_payload(self) -> None:
        summary = DashboardSummary(
            total_reports=1204,
            total_incidents=154,
            total_actors=12,
            reports_by_year=[DashboardYearCount(year=2024, count=318)],
            incidents_by_motivation=[DashboardMotivationCount(motivation="financial", count=81)],
            top_groups=[DashboardTopGroup(group_id=3, name="Lazarus Group", report_count=412)],
        )
        assert summary.total_reports == 1204
        assert summary.top_groups[0].name == "Lazarus Group"

    def test_summary_aggregates_default_empty(self) -> None:
        summary = DashboardSummary(total_reports=0, total_incidents=0, total_actors=0)
        assert summary.reports_by_year == []
        assert summary.incidents_by_motivation == []
        assert summary.top_groups == []

    def test_summary_rejects_negative_totals(self) -> None:
        with pytest.raises(ValidationError):
            DashboardSummary(total_reports=-1, total_incidents=0, total_actors=0)


# ---------------------------------------------------------------------------
# OpenAPI examples — plan D13 (DTO-level happy/empty)
# ---------------------------------------------------------------------------


class TestOpenAPIExamples:
    @pytest.mark.parametrize(
        "dto_cls",
        [
            ReportItem,
            IncidentItem,
            ActorItem,
            ReportListResponse,
            IncidentListResponse,
            ActorListResponse,
            DashboardSummary,
            DashboardYearCount,
            DashboardMotivationCount,
            DashboardTopGroup,
        ],
    )
    def test_dto_exposes_examples_in_json_schema(self, dto_cls: type) -> None:
        """Every read-surface DTO must carry at least one example
        payload in its JSON schema — so that `/openapi.json` + Swagger
        /docs + Redoc all render meaningful examples (plan D13). If
        this regresses, the OpenAPI UX degrades silently."""
        schema = dto_cls.model_json_schema()
        assert "examples" in schema, f"{dto_cls.__name__} has no examples"
        assert len(schema["examples"]) >= 1

    def test_list_envelopes_include_empty_example(self) -> None:
        """List envelopes must also carry the empty-page example
        (per plan D13 happy + empty at DTO layer). 429 / 422 are
        router-level and land in Group B+."""
        for dto_cls in (ReportListResponse, IncidentListResponse, ActorListResponse):
            schema = dto_cls.model_json_schema()
            examples = schema["examples"]
            assert any(
                isinstance(ex, dict) and ex.get("items") == [] for ex in examples
            ), f"{dto_cls.__name__} missing empty example"


# ---------------------------------------------------------------------------
# Isolation — no auth DTO leakage
# ---------------------------------------------------------------------------


class TestAuthDTOIsolation:
    def test_read_module_does_not_redefine_currentuser(self) -> None:
        """Plan D10 forbids widening the /auth/me response. Guard
        against someone accidentally adding a CurrentUser-shaped
        DTO to the read module — if this import succeeds, the
        read module grew auth fields it should not own."""
        import api.schemas.read as read_schemas

        assert not hasattr(read_schemas, "CurrentUser")
        assert not hasattr(read_schemas, "UserInfo")
        assert not hasattr(read_schemas, "AuthMe")

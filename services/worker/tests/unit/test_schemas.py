"""Tests for worker.bootstrap.schemas."""

from __future__ import annotations

import datetime as dt

import pytest

from worker.bootstrap.schemas import (
    ActorRow,
    IncidentRow,
    ReportRow,
    RowValidationError,
)


# ---------------------------------------------------------------------------
# ActorRow
# ---------------------------------------------------------------------------


def test_actor_happy_path() -> None:
    row = ActorRow(
        name="Lazarus Group",
        named_by="Kaspersky",
        associated_group="Lazarus",
        first_seen=dt.date(2009, 2, 1),
        last_seen=dt.date(2025, 12, 15),
    )
    assert row.name == "Lazarus Group"
    assert row.associated_group == "Lazarus"
    assert row.first_seen == dt.date(2009, 2, 1)


def test_actor_optional_fields_default_to_none() -> None:
    row = ActorRow(name="Lazarus")
    assert row.named_by is None
    assert row.associated_group is None
    assert row.first_seen is None
    assert row.last_seen is None


def test_actor_accepts_datetime_and_coerces_to_date() -> None:
    row = ActorRow(
        name="Lazarus",
        first_seen=dt.datetime(2015, 6, 1, 12, 0, 0),
    )
    assert row.first_seen == dt.date(2015, 6, 1)


def test_actor_accepts_iso_string_date() -> None:
    row = ActorRow(name="Lazarus", first_seen="2020-01-15")
    assert row.first_seen == dt.date(2020, 1, 15)


def test_actor_empty_string_name_rejected() -> None:
    with pytest.raises(RowValidationError):
        ActorRow(name="")


def test_actor_whitespace_only_name_rejected() -> None:
    with pytest.raises(RowValidationError):
        ActorRow(name="   ")


def test_actor_missing_name_rejected() -> None:
    with pytest.raises(RowValidationError):
        ActorRow()  # type: ignore[call-arg]


def test_actor_unknown_field_rejected() -> None:
    with pytest.raises(RowValidationError):
        ActorRow(name="Lazarus", secret_field="nope")  # type: ignore[call-arg]


def test_actor_associated_group_can_be_unknown_alias() -> None:
    """The schema must pass unknown aliases through untouched — the
    alias dictionary is applied in a later normalization step."""
    row = ActorRow(name="X", associated_group="NonExistentGroup")
    assert row.associated_group == "NonExistentGroup"


# ---------------------------------------------------------------------------
# ReportRow
# ---------------------------------------------------------------------------


def test_report_happy_path() -> None:
    row = ReportRow(
        published=dt.date(2024, 3, 15),
        author="Mandiant",
        title="Lazarus returns with new macOS backdoor",
        url="https://example.com/threat/lazarus-macos-2024",
        tags="#lazarus #malware #appleseed #cve-2024-1234",
    )
    assert row.url.startswith("https://")
    assert row.published == dt.date(2024, 3, 15)


def test_report_accepts_url_with_query_string() -> None:
    row = ReportRow(
        published=dt.date(2025, 1, 1),
        title="Report",
        url="https://example.com/x?utm_source=newsletter&utm_campaign=march",
    )
    assert "utm_source" in row.url


def test_report_missing_title_rejected() -> None:
    with pytest.raises(RowValidationError):
        ReportRow(
            published=dt.date(2024, 3, 15),
            title="",
            url="https://example.com/x",
        )


def test_report_missing_published_rejected() -> None:
    with pytest.raises(RowValidationError):
        ReportRow(  # type: ignore[call-arg]
            title="x",
            url="https://example.com/x",
        )


def test_report_null_published_rejected() -> None:
    with pytest.raises(RowValidationError):
        ReportRow(
            published=None,  # type: ignore[arg-type]
            title="x",
            url="https://example.com/x",
        )


def test_report_missing_url_rejected() -> None:
    with pytest.raises(RowValidationError):
        ReportRow(  # type: ignore[call-arg]
            published=dt.date(2024, 1, 1),
            title="x",
        )


@pytest.mark.parametrize(
    "bad_url",
    [
        "not-a-url",
        "ftp://example.com/x",
        "example.com/x",
        "https://",
        "http://",
        "",
    ],
)
def test_report_invalid_url_rejected(bad_url: str) -> None:
    with pytest.raises(RowValidationError):
        ReportRow(
            published=dt.date(2024, 1, 1),
            title="x",
            url=bad_url,
        )


def test_report_tags_optional() -> None:
    row = ReportRow(
        published=dt.date(2024, 1, 1),
        title="x",
        url="https://example.com/x",
    )
    assert row.tags is None


def test_report_coerces_datetime_published_to_date() -> None:
    row = ReportRow(
        published=dt.datetime(2024, 3, 15, 14, 30, 0),
        title="x",
        url="https://example.com/x",
    )
    assert row.published == dt.date(2024, 3, 15)


# ---------------------------------------------------------------------------
# IncidentRow
# ---------------------------------------------------------------------------


def test_incident_happy_path() -> None:
    row = IncidentRow(
        reported=dt.date(2022, 3, 23),
        victims="Ronin Network",
        motivations="financial",
        sectors="crypto",
        countries="VN",
    )
    assert row.countries == "VN"


def test_incident_null_reported_rejected() -> None:
    with pytest.raises(RowValidationError):
        IncidentRow(
            reported=None,  # type: ignore[arg-type]
            victims="Undated Incident",
        )


def test_incident_missing_reported_rejected() -> None:
    with pytest.raises(RowValidationError):
        IncidentRow(  # type: ignore[call-arg]
            victims="x",
        )


def test_incident_missing_victims_rejected() -> None:
    with pytest.raises(RowValidationError):
        IncidentRow(  # type: ignore[call-arg]
            reported=dt.date(2024, 1, 1),
        )


def test_incident_empty_victims_rejected() -> None:
    with pytest.raises(RowValidationError):
        IncidentRow(
            reported=dt.date(2024, 1, 1),
            victims="",
        )


@pytest.mark.parametrize(
    "country",
    ["US", "KR", "JP", "VN", "BD", "GB", "HK", "HK", "DE", "FR"],
)
def test_incident_accepts_real_iso_codes(country: str) -> None:
    row = IncidentRow(
        reported=dt.date(2024, 1, 1),
        victims="x",
        countries=country,
    )
    assert row.countries == country


def test_incident_uppercases_lowercase_country() -> None:
    row = IncidentRow(
        reported=dt.date(2024, 1, 1),
        victims="x",
        countries="kr",
    )
    assert row.countries == "KR"


@pytest.mark.parametrize(
    "bad_country",
    [
        "XX",  # user-assigned range
        "XA",  # user-assigned range
        "XZ",  # user-assigned range
        "123",
        "U",
        "USA",
        "K-R",
        "kR1",
    ],
)
def test_incident_invalid_country_rejected(bad_country: str) -> None:
    with pytest.raises(RowValidationError):
        IncidentRow(
            reported=dt.date(2024, 1, 1),
            victims="x",
            countries=bad_country,
        )


def test_incident_empty_country_becomes_none() -> None:
    row = IncidentRow(
        reported=dt.date(2024, 1, 1),
        victims="x",
        countries="",
    )
    assert row.countries is None


def test_incident_none_country_stays_none() -> None:
    row = IncidentRow(
        reported=dt.date(2024, 1, 1),
        victims="x",
        countries=None,
    )
    assert row.countries is None

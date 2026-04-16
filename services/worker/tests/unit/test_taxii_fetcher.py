"""Tests for worker.ingest.taxii.fetcher — TAXII 2.1 collection fetcher.

Covers:
  - added_after exclusive + 5-min overlap (decision H)
  - Mandatory pagination (decision I)
  - max_pages safety (decision I)
  - httpx only, no new deps (decision A)
  - Auth header injection (decision D1)
  - Content-Type validation (PR #8 NonXMLContentType lesson)
  - Mid-pagination failure: objects from earlier pages returned,
    is_complete=False so runner must not advance state
"""

from __future__ import annotations

import base64
import datetime as dt
import json

import httpx
import pytest

from worker.ingest.taxii.config import TaxiiCollectionConfig
from worker.ingest.taxii.fetcher import (
    CollectionFetchOutcome,
    TaxiiFetcher,
    compute_added_after,
)
from worker.ingest.taxii.state import CollectionStateRow


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_TAXII_CT = "application/taxii+json;version=2.1"
_JSON_CT = "application/json"


def _make_config(**overrides) -> TaxiiCollectionConfig:
    base = {
        "slug": "test-col",
        "display_name": "Test",
        "server_url": "https://taxii.example.com",
        "api_root_path": "/api/",
        "collection_id": "col-1",
        "max_pages": 100,
    }
    base.update(overrides)
    return TaxiiCollectionConfig(**base)


def _make_state(**overrides) -> CollectionStateRow:
    base = {
        "collection_key": "test-col",
        "server_url": "https://taxii.example.com",
        "collection_id": "col-1",
        "last_added_after": "2026-04-16T10:00:00+00:00",
        "last_fetched_at": None,
        "last_object_count": None,
        "last_error": None,
        "consecutive_failures": 0,
    }
    base.update(overrides)
    return CollectionStateRow(**base)


def _stix_object(type_: str = "intrusion-set", id_suffix: str = "001") -> dict:
    return {
        "type": type_,
        "id": f"{type_}--00000000-0000-0000-0000-{id_suffix:>012}",
        "name": f"Test {type_} {id_suffix}",
        "created": "2026-01-01T00:00:00Z",
        "modified": "2026-04-15T00:00:00Z",
    }


def _envelope(
    objects: list[dict] | None = None,
    more: bool = False,
    next_param: str | None = None,
) -> dict:
    env: dict = {"objects": objects or []}
    if more:
        env["more"] = True
    if next_param is not None:
        env["next"] = next_param
    return env


# ---------------------------------------------------------------------------
# compute_added_after — decision H
# ---------------------------------------------------------------------------


def test_compute_added_after_none_on_no_state() -> None:
    assert compute_added_after(None) is None


def test_compute_added_after_none_on_null_timestamp() -> None:
    state = _make_state(last_added_after=None)
    assert compute_added_after(state) is None


def test_compute_added_after_subtracts_5_minutes() -> None:
    state = _make_state(last_added_after="2026-04-16T10:00:00+00:00")
    result = compute_added_after(state)
    assert result is not None
    ts = dt.datetime.fromisoformat(result)
    expected = dt.datetime(2026, 4, 16, 9, 55, 0, tzinfo=dt.timezone.utc)
    assert ts == expected


def test_compute_added_after_handles_naive_timestamp() -> None:
    """Naive timestamps are treated as UTC per the docstring."""
    state = _make_state(last_added_after="2026-04-16T10:00:00")
    result = compute_added_after(state)
    assert result is not None
    ts = dt.datetime.fromisoformat(result)
    assert ts.tzinfo is not None


def test_compute_added_after_preserves_subsecond() -> None:
    state = _make_state(last_added_after="2026-04-16T10:00:00.123456+00:00")
    result = compute_added_after(state)
    assert result is not None
    ts = dt.datetime.fromisoformat(result)
    expected = dt.datetime(
        2026, 4, 16, 9, 55, 0, 123456, tzinfo=dt.timezone.utc,
    )
    assert ts == expected


# ---------------------------------------------------------------------------
# Single page — happy path
# ---------------------------------------------------------------------------


async def test_fetch_single_page_success() -> None:
    objects = [_stix_object("intrusion-set", "001"), _stix_object("malware", "002")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(objects=objects, more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert outcome.is_success
    assert outcome.is_complete
    assert len(outcome.objects) == 2
    assert outcome.pages_fetched == 1
    assert outcome.max_pages_reached is False
    assert outcome.error is None


async def test_fetch_empty_collection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(objects=[], more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert outcome.is_success
    assert outcome.is_complete
    assert len(outcome.objects) == 0
    assert outcome.pages_fetched == 1


# ---------------------------------------------------------------------------
# Pagination — mandatory (decision I)
# ---------------------------------------------------------------------------


async def test_fetch_multi_page_collects_all_objects() -> None:
    """3-page fetch: page1 (2 objects) -> page2 (1 object) -> page3 (1 object)."""
    page_data = {
        None: _envelope(
            [_stix_object("intrusion-set", "001"), _stix_object("malware", "002")],
            more=True, next_param="page2",
        ),
        "page2": _envelope(
            [_stix_object("tool", "003")],
            more=True, next_param="page3",
        ),
        "page3": _envelope(
            [_stix_object("campaign", "004")],
            more=False,
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        next_val = request.url.params.get("next")
        body = page_data.get(next_val, page_data[None])
        return httpx.Response(
            200, json=body, headers={"Content-Type": _TAXII_CT},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert outcome.is_success
    assert outcome.is_complete
    assert len(outcome.objects) == 4
    assert outcome.pages_fetched == 3
    assert outcome.max_pages_reached is False


# ---------------------------------------------------------------------------
# max_pages safety — decision I
# ---------------------------------------------------------------------------


async def test_more_true_without_next_is_incomplete() -> None:
    """P1 Codex R1: more=true without next token = server error, not complete."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope(
                [_stix_object("malware", "001")],
                more=True,
                # next_param intentionally omitted
            ),
            headers={"Content-Type": _TAXII_CT},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success  # Error set
    assert not outcome.is_complete  # NOT complete
    assert "more=true but no 'next'" in (outcome.error or "")
    assert len(outcome.objects) == 1  # Objects from page 1 preserved


async def test_max_pages_terminates_infinite_pagination() -> None:
    """Server always returns more=True — fetcher stops at max_pages."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json=_envelope(
                [_stix_object("malware", str(call_count).zfill(3))],
                more=True,
                next_param=f"page{call_count + 1}",
            ),
            headers={"Content-Type": _TAXII_CT},
        )

    config = _make_config(max_pages=3)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(config)

    assert outcome.is_success  # No HTTP error occurred
    assert not outcome.is_complete  # But not complete — truncated
    assert outcome.max_pages_reached is True
    assert outcome.pages_fetched == 3
    assert len(outcome.objects) == 3
    assert call_count == 3  # Exactly max_pages requests made


async def test_max_pages_natural_completion_not_flagged() -> None:
    """If collection completes within max_pages, max_pages_reached is False."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope([_stix_object("tool", "001")], more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    config = _make_config(max_pages=1)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(config)

    assert outcome.is_complete
    assert outcome.max_pages_reached is False


# ---------------------------------------------------------------------------
# added_after overlap in actual request — decision H
# ---------------------------------------------------------------------------


async def test_added_after_sent_with_overlap() -> None:
    """Verify the request includes added_after = last - 5min."""
    captured_params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_params.append(dict(request.url.params))
        return httpx.Response(
            200,
            json=_envelope([], more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    state = _make_state(last_added_after="2026-04-16T10:00:00+00:00")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        await fetcher.fetch_collection(_make_config(), state=state)

    assert len(captured_params) == 1
    aa = captured_params[0].get("added_after")
    assert aa is not None
    ts = dt.datetime.fromisoformat(aa)
    expected = dt.datetime(2026, 4, 16, 9, 55, 0, tzinfo=dt.timezone.utc)
    assert ts == expected


async def test_no_added_after_on_first_poll() -> None:
    """First poll (no state) omits added_after entirely → full pull."""
    captured_params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_params.append(dict(request.url.params))
        return httpx.Response(
            200,
            json=_envelope([], more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        await fetcher.fetch_collection(_make_config(), state=None)

    assert "added_after" not in captured_params[0]


async def test_added_after_included_on_paginated_requests() -> None:
    """added_after should be on all pages (initial + paginated)."""
    captured_params: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_params.append(dict(request.url.params))
        next_val = request.url.params.get("next")
        if next_val is None:
            return httpx.Response(
                200,
                json=_envelope([_stix_object()], more=True, next_param="p2"),
                headers={"Content-Type": _TAXII_CT},
            )
        return httpx.Response(
            200,
            json=_envelope([_stix_object()], more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    state = _make_state(last_added_after="2026-04-16T10:00:00+00:00")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        await fetcher.fetch_collection(_make_config(), state=state)

    assert len(captured_params) == 2
    assert "added_after" in captured_params[0]
    assert "added_after" in captured_params[1]


# ---------------------------------------------------------------------------
# Auth header injection — decision D1
# ---------------------------------------------------------------------------


async def test_auth_none_no_auth_header() -> None:
    captured_headers: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(dict(request.headers))
        return httpx.Response(
            200,
            json=_envelope([], more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    config = _make_config(auth_type="none")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        await fetcher.fetch_collection(config)

    assert "authorization" not in captured_headers[0]


async def test_auth_basic_sends_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_PASSWORD", "secret")
    captured_headers: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(dict(request.headers))
        return httpx.Response(
            200,
            json=_envelope([], more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    config = _make_config(
        auth_type="basic",
        username="admin",
        password_env="TEST_PASSWORD",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        await fetcher.fetch_collection(config)

    auth = captured_headers[0].get("authorization", "")
    assert auth.startswith("Basic ")
    decoded = base64.b64decode(auth.split(" ", 1)[1]).decode()
    assert decoded == "admin:secret"


async def test_auth_header_api_key_sends_custom_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_API_KEY", "key-xyz-123")
    captured_headers: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(dict(request.headers))
        return httpx.Response(
            200,
            json=_envelope([], more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    config = _make_config(
        auth_type="header_api_key",
        auth_header_name="X-Api-Key",
        auth_header_value_env="TEST_API_KEY",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        await fetcher.fetch_collection(config)

    assert captured_headers[0].get("x-api-key") == "key-xyz-123"


# ---------------------------------------------------------------------------
# Content-Type validation — PR #8 NonXMLContentType lesson
# ---------------------------------------------------------------------------


async def test_html_content_type_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html><body>Login page</body></html>",
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success
    assert "non-TAXII Content-Type" in (outcome.error or "")
    assert "text/html" in (outcome.error or "")


async def test_application_json_accepted() -> None:
    """Some TAXII servers return application/json instead of application/taxii+json."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope([_stix_object()], more=False),
            headers={"Content-Type": _JSON_CT},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert outcome.is_success
    assert len(outcome.objects) == 1


# ---------------------------------------------------------------------------
# HTTP error responses
# ---------------------------------------------------------------------------


async def test_http_500_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success
    assert "HTTP 500" in (outcome.error or "")
    assert outcome.pages_fetched == 0


async def test_http_404_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success
    assert "HTTP 404" in (outcome.error or "")


async def test_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success
    assert "timeout" in (outcome.error or "").lower()


async def test_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success
    assert "connection refused" in (outcome.error or "").lower()


# ---------------------------------------------------------------------------
# Mid-pagination failure — critical: partial objects returned,
# is_complete=False, state must NOT advance
# ---------------------------------------------------------------------------


async def test_mid_pagination_failure_returns_partial_objects() -> None:
    """Page 1 succeeds (2 objects), page 2 returns 500.

    Outcome should have 2 objects from page 1, error set,
    is_complete=False, pages_fetched=1.
    """
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                200,
                json=_envelope(
                    [_stix_object("intrusion-set", "001"),
                     _stix_object("malware", "002")],
                    more=True,
                    next_param="page2",
                ),
                headers={"Content-Type": _TAXII_CT},
            )
        # Page 2 fails
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success
    assert not outcome.is_complete
    assert len(outcome.objects) == 2  # Page 1 objects preserved
    assert outcome.pages_fetched == 1  # Only page 1 counted
    assert "HTTP 500" in (outcome.error or "")
    assert "page 2" in (outcome.error or "")


async def test_mid_pagination_timeout_returns_partial() -> None:
    """Page 1 succeeds, page 2 times out."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                200,
                json=_envelope(
                    [_stix_object("tool", "001")],
                    more=True,
                    next_param="page2",
                ),
                headers={"Content-Type": _TAXII_CT},
            )
        raise httpx.ReadTimeout("timeout on page 2")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success
    assert not outcome.is_complete
    assert len(outcome.objects) == 1
    assert outcome.pages_fetched == 1


async def test_mid_pagination_content_type_rejection() -> None:
    """Page 1 OK, page 2 returns HTML (WAF redirect)."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                200,
                json=_envelope(
                    [_stix_object("campaign", "001")],
                    more=True,
                    next_param="page2",
                ),
                headers={"Content-Type": _TAXII_CT},
            )
        return httpx.Response(
            200,
            content=b"<html>WAF</html>",
            headers={"Content-Type": "text/html"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success
    assert not outcome.is_complete
    assert len(outcome.objects) == 1
    assert "non-TAXII Content-Type" in (outcome.error or "")


# ---------------------------------------------------------------------------
# Invalid JSON / malformed envelope
# ---------------------------------------------------------------------------


async def test_invalid_json_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"not json at all",
            headers={"Content-Type": _TAXII_CT},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success
    assert "invalid JSON" in (outcome.error or "")


async def test_envelope_not_dict() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"type": "intrusion-set"}],  # list, not dict
            headers={"Content-Type": _TAXII_CT},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success
    assert "not a JSON object" in (outcome.error or "")


async def test_envelope_objects_not_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"objects": "not a list"},
            headers={"Content-Type": _TAXII_CT},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    assert not outcome.is_success
    assert "not a list" in (outcome.error or "")


# ---------------------------------------------------------------------------
# Accept header sent on every request
# ---------------------------------------------------------------------------


async def test_accept_header_sent() -> None:
    captured_headers: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(dict(request.headers))
        return httpx.Response(
            200,
            json=_envelope([], more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        await fetcher.fetch_collection(_make_config())

    assert captured_headers[0].get("accept") == "application/taxii+json;version=2.1"


# ---------------------------------------------------------------------------
# fetch_timestamp is set for state management
# ---------------------------------------------------------------------------


async def test_fetch_timestamp_is_iso_utc() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_envelope([], more=False),
            headers={"Content-Type": _TAXII_CT},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = TaxiiFetcher(client=client)
        outcome = await fetcher.fetch_collection(_make_config())

    ts = dt.datetime.fromisoformat(outcome.fetch_timestamp)
    assert ts.tzinfo is not None


# ---------------------------------------------------------------------------
# CollectionFetchOutcome properties
# ---------------------------------------------------------------------------


def test_outcome_is_success_true_on_no_error() -> None:
    outcome = CollectionFetchOutcome(
        collection_key="x", objects=(), pages_fetched=1,
        max_pages_reached=False, fetch_timestamp="t", error=None,
    )
    assert outcome.is_success


def test_outcome_is_success_false_on_error() -> None:
    outcome = CollectionFetchOutcome(
        collection_key="x", objects=(), pages_fetched=0,
        max_pages_reached=False, fetch_timestamp="t", error="fail",
    )
    assert not outcome.is_success


def test_outcome_is_complete_false_on_max_pages() -> None:
    outcome = CollectionFetchOutcome(
        collection_key="x", objects=(), pages_fetched=3,
        max_pages_reached=True, fetch_timestamp="t", error=None,
    )
    assert outcome.is_success  # No error
    assert not outcome.is_complete  # But truncated


def test_outcome_is_complete_false_on_error() -> None:
    outcome = CollectionFetchOutcome(
        collection_key="x", objects=(), pages_fetched=1,
        max_pages_reached=False, fetch_timestamp="t", error="fail",
    )
    assert not outcome.is_complete


def test_outcome_is_complete_true_on_success_no_truncation() -> None:
    outcome = CollectionFetchOutcome(
        collection_key="x", objects=(_stix_object(),), pages_fetched=1,
        max_pages_reached=False, fetch_timestamp="t", error=None,
    )
    assert outcome.is_complete

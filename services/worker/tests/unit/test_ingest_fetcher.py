"""Tests for worker.ingest.fetcher — httpx fetch with ETag/Last-Modified."""

from __future__ import annotations

import pytest
import httpx

from worker.ingest.config import FeedConfig
from worker.ingest.feed_state import FeedStateRow
from worker.ingest.fetcher import FetchOutcome, RssFetcher


SAMPLE_XML = b"<rss><channel><title>Test</title></channel></rss>"
FEED = FeedConfig(
    slug="test-feed",
    display_name="Test Feed",
    url="https://example.com/feed.xml",
    kind="rss",
)


def _state(
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    failures: int = 0,
) -> FeedStateRow:
    return FeedStateRow(
        feed_slug="test-feed",
        etag=etag,
        last_modified=last_modified,
        last_fetched_at=None,
        last_status_code=200,
        last_error=None,
        consecutive_failures=failures,
    )


def _mock_client(handler) -> httpx.AsyncClient:  # noqa: ANN001
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# 200 + body
# ---------------------------------------------------------------------------


async def test_fetch_200_returns_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=SAMPLE_XML)

    fetcher = RssFetcher(client=_mock_client(handler))
    outcome = await fetcher.fetch(FEED)

    assert outcome.is_success
    assert outcome.is_ok
    assert outcome.content == SAMPLE_XML
    assert outcome.status_code == 200
    assert outcome.error is None


async def test_fetch_200_captures_etag_and_last_modified() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=SAMPLE_XML,
            headers={"ETag": '"abc123"', "Last-Modified": "Tue, 15 Apr 2026 10:00:00 GMT"},
        )

    fetcher = RssFetcher(client=_mock_client(handler))
    outcome = await fetcher.fetch(FEED)

    assert outcome.etag == '"abc123"'
    assert outcome.last_modified == "Tue, 15 Apr 2026 10:00:00 GMT"


# ---------------------------------------------------------------------------
# 304 Not Modified
# ---------------------------------------------------------------------------


async def test_fetch_304_returns_no_content() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    fetcher = RssFetcher(client=_mock_client(handler))
    outcome = await fetcher.fetch(FEED)

    assert outcome.is_not_modified
    assert outcome.is_ok
    assert not outcome.is_success
    assert outcome.content is None
    assert outcome.error is None


async def test_fetch_sends_if_none_match_when_state_has_etag() -> None:
    captured_headers: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(304)

    state = _state(etag='"abc123"')
    fetcher = RssFetcher(client=_mock_client(handler))
    await fetcher.fetch(FEED, state=state)

    assert captured_headers.get("if-none-match") == '"abc123"'


async def test_fetch_sends_if_modified_since_when_state_has_last_modified() -> None:
    captured_headers: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(304)

    state = _state(last_modified="Tue, 15 Apr 2026 10:00:00 GMT")
    fetcher = RssFetcher(client=_mock_client(handler))
    await fetcher.fetch(FEED, state=state)

    assert captured_headers.get("if-modified-since") == "Tue, 15 Apr 2026 10:00:00 GMT"


async def test_fetch_304_preserves_previous_etag_when_server_omits() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(304)

    state = _state(etag='"old"')
    fetcher = RssFetcher(client=_mock_client(handler))
    outcome = await fetcher.fetch(FEED, state=state)

    assert outcome.etag == '"old"'


# ---------------------------------------------------------------------------
# ETag round-trip: set -> next fetch sends If-None-Match -> 304
# ---------------------------------------------------------------------------


async def test_etag_round_trip() -> None:
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                200, content=SAMPLE_XML, headers={"ETag": '"v1"'}
            )
        assert request.headers.get("if-none-match") == '"v1"'
        return httpx.Response(304)

    fetcher = RssFetcher(client=_mock_client(handler))

    first = await fetcher.fetch(FEED)
    assert first.is_success
    assert first.etag == '"v1"'

    state = _state(etag=first.etag)
    second = await fetcher.fetch(FEED, state=state)
    assert second.is_not_modified
    assert call_count == 2


# ---------------------------------------------------------------------------
# HTTP error responses
# ---------------------------------------------------------------------------


async def test_fetch_500_returns_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    fetcher = RssFetcher(client=_mock_client(handler))
    outcome = await fetcher.fetch(FEED)

    assert not outcome.is_ok
    assert outcome.status_code == 500
    assert outcome.content is None
    assert outcome.error == "HTTP 500"


async def test_fetch_403_returns_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    fetcher = RssFetcher(client=_mock_client(handler))
    outcome = await fetcher.fetch(FEED)

    assert not outcome.is_ok
    assert outcome.error == "HTTP 403"


# ---------------------------------------------------------------------------
# Network errors
# ---------------------------------------------------------------------------


async def test_fetch_timeout_returns_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    fetcher = RssFetcher(client=_mock_client(handler), timeout=5.0)
    outcome = await fetcher.fetch(FEED)

    assert not outcome.is_ok
    assert outcome.status_code is None
    assert outcome.content is None
    assert "timeout" in outcome.error.lower()


async def test_fetch_connection_error_returns_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    fetcher = RssFetcher(client=_mock_client(handler))
    outcome = await fetcher.fetch(FEED)

    assert not outcome.is_ok
    assert outcome.status_code is None
    assert outcome.error is not None


async def test_fetch_network_error_preserves_previous_state() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    state = _state(etag='"old"', last_modified="Tue, 01 Jan 2026 00:00:00 GMT")
    fetcher = RssFetcher(client=_mock_client(handler))
    outcome = await fetcher.fetch(FEED, state=state)

    assert outcome.etag == '"old"'
    assert outcome.last_modified == "Tue, 01 Jan 2026 00:00:00 GMT"


# ---------------------------------------------------------------------------
# No state (first poll)
# ---------------------------------------------------------------------------


async def test_fetch_without_state_sends_no_conditional_headers() -> None:
    captured_headers: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(200, content=SAMPLE_XML)

    fetcher = RssFetcher(client=_mock_client(handler))
    await fetcher.fetch(FEED, state=None)

    assert "if-none-match" not in captured_headers
    assert "if-modified-since" not in captured_headers


async def test_fetch_sends_user_agent() -> None:
    captured_headers: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(200, content=SAMPLE_XML)

    fetcher = RssFetcher(client=_mock_client(handler))
    await fetcher.fetch(FEED)

    assert "dprk-cti-worker" in captured_headers.get("user-agent", "")


# ---------------------------------------------------------------------------
# Boundary: fetcher never calls feedparser
# ---------------------------------------------------------------------------


async def test_fetch_outcome_content_is_raw_bytes() -> None:
    payload = b"<?xml version='1.0'?><rss><channel></channel></rss>"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    fetcher = RssFetcher(client=_mock_client(handler))
    outcome = await fetcher.fetch(FEED)

    assert isinstance(outcome.content, bytes)
    assert outcome.content == payload

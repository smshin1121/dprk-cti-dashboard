"""RSS feed fetcher — httpx only, returns raw bytes.

The fetcher is the HTTP boundary of the ingest pipeline. It handles
conditional-GET headers (ETag / Last-Modified), timeouts, and error
classification. It NEVER parses feed content — that responsibility
belongs to the parser module (Group C).

Per D5: ``feedparser.parse(url)`` is forbidden. The fetcher returns
bytes which the parser receives via ``feedparser.parse(content)``.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from worker.ingest.config import FeedConfig
from worker.ingest.feed_state import FeedStateRow


__all__ = [
    "FetchOutcome",
    "RssFetcher",
]


_DEFAULT_TIMEOUT = 30.0
_USER_AGENT = "dprk-cti-worker/0.1"


@dataclass(frozen=True, slots=True)
class FetchOutcome:
    """Result of a single feed fetch attempt.

    ``content`` is ``None`` when the server returns 304 (not modified)
    or when the request fails entirely. Check ``status_code`` and
    ``error`` to distinguish.
    """

    status_code: int | None
    content: bytes | None
    etag: str | None
    last_modified: str | None
    error: str | None

    @property
    def is_not_modified(self) -> bool:
        return self.status_code == 304

    @property
    def is_success(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300

    @property
    def is_ok(self) -> bool:
        return self.is_success or self.is_not_modified


class RssFetcher:
    """Async fetcher wrapping ``httpx.AsyncClient``.

    Inject a custom ``httpx.AsyncClient`` for testing via the
    ``client`` constructor parameter (e.g. with ``MockTransport``).
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._timeout = timeout

    async def fetch(
        self,
        feed: FeedConfig,
        state: FeedStateRow | None = None,
    ) -> FetchOutcome:
        """Fetch a single feed, returning raw bytes on success."""
        headers: dict[str, str] = {"User-Agent": _USER_AGENT}
        if state is not None:
            if state.etag:
                headers["If-None-Match"] = state.etag
            if state.last_modified:
                headers["If-Modified-Since"] = state.last_modified

        try:
            response = await self._client.get(
                feed.url,
                headers=headers,
                timeout=self._timeout,
                follow_redirects=True,
            )
        except httpx.TimeoutException:
            return FetchOutcome(
                status_code=None,
                content=None,
                etag=state.etag if state else None,
                last_modified=state.last_modified if state else None,
                error=f"timeout after {self._timeout}s",
            )
        except httpx.HTTPError as exc:
            return FetchOutcome(
                status_code=None,
                content=None,
                etag=state.etag if state else None,
                last_modified=state.last_modified if state else None,
                error=str(exc),
            )

        resp_etag = response.headers.get("ETag")
        resp_last_modified = response.headers.get("Last-Modified")

        if response.status_code == 304:
            return FetchOutcome(
                status_code=304,
                content=None,
                etag=resp_etag or (state.etag if state else None),
                last_modified=resp_last_modified or (state.last_modified if state else None),
                error=None,
            )

        if response.status_code >= 400:
            return FetchOutcome(
                status_code=response.status_code,
                content=None,
                etag=resp_etag or (state.etag if state else None),
                last_modified=resp_last_modified or (state.last_modified if state else None),
                error=f"HTTP {response.status_code}",
            )

        return FetchOutcome(
            status_code=response.status_code,
            content=response.content,
            etag=resp_etag,
            last_modified=resp_last_modified,
            error=None,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

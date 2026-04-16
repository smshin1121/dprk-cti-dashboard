"""TAXII 2.1 collection fetcher — httpx only, returns raw STIX envelopes.

The fetcher is the HTTP boundary of the TAXII ingest pipeline. It handles
TAXII 2.1 content negotiation, pagination (mandatory per decision I),
``added_after`` incremental polling with 5-minute overlap (decision H),
and auth header injection (decision D1).

It NEVER writes to the database. State updates are the runner's
responsibility — state must only advance after the **entire** collection
fetch succeeds (user requirement: partial page failure must not advance
``last_added_after``).

Per decision A: no ``taxii2-client`` dependency. TAXII 2.1 is HTTP + JSON;
this module implements the protocol surface (~120 LOC) directly over httpx.

Content-Type validation (PR #8 NonXMLContentType lesson): non-TAXII
responses (HTML login pages, WAF blocks) are classified as hard errors.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import httpx

from worker.ingest.taxii.config import TaxiiCollectionConfig
from worker.ingest.taxii.state import CollectionStateRow


__all__ = [
    "CollectionFetchOutcome",
    "TaxiiFetcher",
    "compute_added_after",
]


_TAXII_ACCEPT = "application/taxii+json;version=2.1"
_OVERLAP_MINUTES = 5
_USER_AGENT = "dprk-cti-worker/0.1"
_DEFAULT_TIMEOUT = 60.0  # TAXII can be slower than RSS feeds


def _is_taxii_content_type(content_type: str) -> bool:
    """Accept ``application/taxii+json`` and ``application/json``.

    Reject everything else (``text/html`` from WAF, ``text/plain``, etc.).
    """
    ct = content_type.lower().split(";")[0].strip()
    return ct in ("application/taxii+json", "application/json")


def compute_added_after(state: CollectionStateRow | None) -> str | None:
    """Compute the ``added_after`` query parameter for a TAXII request.

    Per decision H:
      - First poll (no state or no ``last_added_after``): return ``None``
        → omit ``added_after`` entirely → full pull.
      - Subsequent polls: subtract a 5-minute overlap window from
        ``last_added_after`` to guard against server-side clock skew
        and boundary edge cases. ``ON CONFLICT DO NOTHING`` deduplicates
        any re-fetched objects silently.

    ``added_after`` is exclusive in TAXII 2.1 (objects added strictly
    AFTER the timestamp are returned).
    """
    if state is None or state.last_added_after is None:
        return None

    ts = dt.datetime.fromisoformat(state.last_added_after)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    overlapped = ts - dt.timedelta(minutes=_OVERLAP_MINUTES)
    return overlapped.isoformat()


@dataclass(frozen=True, slots=True)
class CollectionFetchOutcome:
    """Result of fetching all pages from a single TAXII collection.

    ``objects`` contains all raw STIX dicts from successfully fetched
    pages. On mid-pagination failure, objects from earlier pages are
    still included (they are valid data), but ``error`` is set and
    ``is_complete`` is ``False`` — the runner must NOT advance state.
    """

    collection_key: str
    objects: tuple[dict, ...]
    pages_fetched: int
    max_pages_reached: bool
    fetch_timestamp: str  # ISO-8601 UTC, for state update on success
    error: str | None

    @property
    def is_success(self) -> bool:
        """True if all fetched pages returned valid TAXII responses."""
        return self.error is None

    @property
    def is_complete(self) -> bool:
        """True if the entire collection was fetched without truncation.

        Only when ``is_complete`` may the runner advance
        ``last_added_after`` to ``fetch_timestamp``. If ``max_pages``
        was reached or an error occurred, state must NOT advance.
        """
        return self.error is None and not self.max_pages_reached


class TaxiiFetcher:
    """Async TAXII 2.1 fetcher wrapping ``httpx.AsyncClient``.

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

    async def fetch_collection(
        self,
        config: TaxiiCollectionConfig,
        state: CollectionStateRow | None = None,
    ) -> CollectionFetchOutcome:
        """Fetch all STIX objects from a collection with mandatory pagination.

        Follows ``more``/``next`` pagination to completeness or until
        ``max_pages`` is reached. Each page is validated for Content-Type
        and JSON structure before extracting objects.

        Returns a ``CollectionFetchOutcome`` with all collected objects
        and a success/completion status. Does NOT write to the database.
        """
        added_after = compute_added_after(state)
        fetch_ts = dt.datetime.now(dt.timezone.utc).isoformat()

        # Auth headers from config (D1)
        headers: dict[str, str] = {
            "Accept": _TAXII_ACCEPT,
            "User-Agent": _USER_AGENT,
        }
        headers.update(config.resolve_auth_headers())

        all_objects: list[dict] = []
        pages_fetched = 0
        next_param: str | None = None
        last_more = False

        while pages_fetched < config.max_pages:
            params: dict[str, str] = {}
            if added_after is not None:
                params["added_after"] = added_after
            if next_param is not None:
                params["next"] = next_param

            outcome = await self._fetch_page(
                config.objects_url,
                headers=headers,
                params=params,
                page_num=pages_fetched + 1,
            )

            if outcome.error is not None:
                return CollectionFetchOutcome(
                    collection_key=config.slug,
                    objects=tuple(all_objects),
                    pages_fetched=pages_fetched,
                    max_pages_reached=False,
                    fetch_timestamp=fetch_ts,
                    error=outcome.error,
                )

            all_objects.extend(outcome.objects)
            pages_fetched += 1
            last_more = outcome.more
            next_param = outcome.next_param

            if not last_more:
                break

            # P1 Codex R1: more=true without next is a server-side error.
            # The collection advertised more data but gave no pagination
            # token — we cannot advance state because we missed objects.
            if next_param is None:
                return CollectionFetchOutcome(
                    collection_key=config.slug,
                    objects=tuple(all_objects),
                    pages_fetched=pages_fetched,
                    max_pages_reached=False,
                    fetch_timestamp=fetch_ts,
                    error=(
                        f"server returned more=true but no 'next' token "
                        f"on page {pages_fetched} — incomplete collection"
                    ),
                )

        # max_pages_reached = loop exhausted AND server indicated more data
        max_pages_reached = last_more and next_param is not None

        return CollectionFetchOutcome(
            collection_key=config.slug,
            objects=tuple(all_objects),
            pages_fetched=pages_fetched,
            max_pages_reached=max_pages_reached,
            fetch_timestamp=fetch_ts,
            error=None,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal: single-page fetch
    # ------------------------------------------------------------------

    async def _fetch_page(
        self,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
        page_num: int,
    ) -> _PageResult:
        """Fetch and validate a single TAXII envelope page."""
        try:
            response = await self._client.get(
                url,
                headers=headers,
                params=params,
                timeout=self._timeout,
                follow_redirects=True,
            )
        except httpx.TimeoutException:
            return _PageResult(
                objects=[],
                more=False,
                next_param=None,
                error=f"timeout after {self._timeout}s on page {page_num}",
            )
        except httpx.HTTPError as exc:
            return _PageResult(
                objects=[],
                more=False,
                next_param=None,
                error=f"HTTP error on page {page_num}: {exc}",
            )

        if response.status_code >= 400:
            return _PageResult(
                objects=[],
                more=False,
                next_param=None,
                error=(
                    f"HTTP {response.status_code} on page {page_num}"
                ),
            )

        # Content-Type validation (PR #8 NonXMLContentType lesson)
        content_type = response.headers.get("content-type", "")
        if not _is_taxii_content_type(content_type):
            return _PageResult(
                objects=[],
                more=False,
                next_param=None,
                error=(
                    f"non-TAXII Content-Type {content_type!r} "
                    f"on page {page_num} (expected application/taxii+json "
                    f"or application/json)"
                ),
            )

        try:
            envelope = response.json()
        except (ValueError, KeyError):
            return _PageResult(
                objects=[],
                more=False,
                next_param=None,
                error=f"invalid JSON on page {page_num}",
            )

        if not isinstance(envelope, dict):
            return _PageResult(
                objects=[],
                more=False,
                next_param=None,
                error=f"envelope is not a JSON object on page {page_num}",
            )

        # P1 Codex R7: require explicit objects field. A generic JSON
        # response (rate-limit, login page) without "objects" should not
        # be treated as a successful empty collection.
        if "objects" not in envelope:
            return _PageResult(
                objects=[],
                more=False,
                next_param=None,
                error=(
                    f"TAXII envelope missing 'objects' field "
                    f"on page {page_num} — not a valid TAXII response"
                ),
            )

        objects = envelope["objects"]
        if not isinstance(objects, list):
            return _PageResult(
                objects=[],
                more=False,
                next_param=None,
                error=f"envelope.objects is not a list on page {page_num}",
            )

        return _PageResult(
            objects=objects,
            more=bool(envelope.get("more", False)),
            next_param=envelope.get("next"),
            error=None,
        )


@dataclass(frozen=True, slots=True)
class _PageResult:
    """Internal result of a single-page fetch. Not exported."""

    objects: list[dict]
    more: bool
    next_param: str | None
    error: str | None

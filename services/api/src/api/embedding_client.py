"""LLM-proxy embedding client — PR #19a Group B (api-side).

Thin ``httpx.AsyncClient`` wrapper over
``POST {base_url}/api/v1/embedding`` on the local llm-proxy service
(see ``services/llm-proxy``, PR #18). Service-local copy of the
worker-side client at
``services/worker/src/worker/bootstrap/embedding_client.py``.

Why duplicated (PR #19a Group B lock): session factory, logging
conventions, and config resolution differ between worker and api.
A shared module would pin those couplings for every future change.
Error-taxonomy classes (``TransientEmbeddingError`` /
``PermanentEmbeddingError``) stay service-local so catch-sites in
the api router never handle worker exceptions or vice versa.

The api caller is the promote route in ``api.routers.reports`` —
after the analyst-approve staging→reports promotion commits, the
router calls ``api.embedding_writer.embed_report`` which uses this
client to populate ``reports.embedding``.

Error taxonomy (plan D5 / D9, locked 2026-04-20):

    - ``httpx.TimeoutException``                     -> ``TransientEmbeddingError``
    - llm-proxy ``429``                              -> ``TransientEmbeddingError``
      (``retry_after_seconds`` parsed from ``Retry-After`` when present)
    - llm-proxy ``502 / 503 / 504``                  -> ``TransientEmbeddingError``
    - llm-proxy ``422``                              -> ``PermanentEmbeddingError``
    - Dimension mismatch (expected ``1536``)         -> ``PermanentEmbeddingError``
    - Malformed 2xx body (items count / shape)       -> ``PermanentEmbeddingError``

Transient errors signal "skip this embed, leave ``embedding=NULL``,
come back to it later" (plan OI2). Permanent errors indicate caller
bug or protocol drift and must not be silenced — they propagate
through to the caller which fails loudly.

Logging posture mirrors PR #18 ``log_schema.py``: only counts,
upstream status codes, and event names — never the raw ``texts``
payload. Upstream error bodies (which may echo caller input) are
never read into log fields.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx


__all__ = [
    "DEFAULT_EMBEDDING_DIMENSIONS",
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingResult",
    "LlmProxyEmbeddingClient",
    "PermanentEmbeddingError",
    "TransientEmbeddingError",
]


logger = logging.getLogger(__name__)


DEFAULT_EMBEDDING_DIMENSIONS = 1536
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_PATH = "/api/v1/embedding"
INTERNAL_TOKEN_HEADER = "X-Internal-Token"


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Happy-path outcome of an ``embed()`` call.

    ``vectors`` is ordered to match the caller's input ``texts``
    regardless of how llm-proxy's upstream ordered the response —
    parsing sorts by ``item.index`` before unpacking.
    """

    vectors: list[list[float]]
    model_returned: str
    cache_hit: bool
    upstream_latency_ms: int


class TransientEmbeddingError(Exception):
    """Recoverable failure — caller leaves ``embedding=NULL`` and may retry later.

    Covers timeouts and llm-proxy ``429 / 502 / 503 / 504``. When
    available, ``retry_after_seconds`` carries the ``Retry-After``
    hint so the backfill CLI can honor it (plan OI4 refinement).
    """

    def __init__(
        self,
        *,
        upstream_status: int | None,
        reason: str,
        retry_after_seconds: int | None = None,
    ) -> None:
        self.upstream_status = upstream_status
        self.retry_after_seconds = retry_after_seconds
        self.reason = reason
        super().__init__(
            f"transient embedding failure "
            f"(status={upstream_status}, reason={reason})"
        )


class PermanentEmbeddingError(Exception):
    """Caller bug / protocol drift — must fail loud (plan D5 ``422`` branch).

    Includes upstream ``422``, dimension mismatches, and malformed
    ``2xx`` bodies. Those indicate a broken contract between worker
    and llm-proxy rather than a transient provider hiccup, so
    silencing them would mask a bug.
    """

    def __init__(
        self,
        *,
        upstream_status: int | None,
        reason: str,
    ) -> None:
        self.upstream_status = upstream_status
        self.reason = reason
        super().__init__(
            f"permanent embedding failure "
            f"(status={upstream_status}, reason={reason})"
        )


class LlmProxyEmbeddingClient:
    """Async client for ``POST {base_url}/api/v1/embedding``.

    The constructor takes an explicit ``httpx.AsyncClient`` so tests
    can inject ``httpx.MockTransport`` without monkey-patching
    module globals. Production wiring builds the client with
    ``timeout=httpx.Timeout(timeout_seconds)``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        internal_token: str,
        client: httpx.AsyncClient,
        timeout_seconds: float,
        default_model: str = DEFAULT_EMBEDDING_MODEL,
        expected_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    ) -> None:
        if not base_url.strip():
            raise ValueError(
                "LlmProxyEmbeddingClient requires a non-empty base_url"
            )
        if not internal_token.strip():
            # Defense in depth — the CLI/caller layer is expected to
            # reject an empty token env, but this guard prevents a
            # constructor typo from producing a token-less request.
            raise ValueError(
                "LlmProxyEmbeddingClient requires a non-empty internal_token"
            )
        self._url = base_url.rstrip("/") + EMBEDDING_PATH
        self._internal_token = internal_token
        self._client = client
        self._timeout_seconds = timeout_seconds
        self._default_model = default_model
        self._expected_dimensions = expected_dimensions

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> EmbeddingResult:
        """Call llm-proxy's embedding endpoint and return vectors.

        Raises ``TransientEmbeddingError`` on timeout / ``429`` /
        ``5xx``. Raises ``PermanentEmbeddingError`` on ``422`` /
        dimension mismatch / malformed ``2xx`` body.

        Input validation (empty list, whitespace-only strings, etc.)
        is the caller's responsibility — that layer knows the
        OI1-locked text-shape rules. If the caller does send bad
        input, llm-proxy will ``422`` and this client will surface
        a ``PermanentEmbeddingError``.
        """
        request_model = model or self._default_model
        body = {"texts": texts, "model": request_model}
        headers = {
            INTERNAL_TOKEN_HEADER: self._internal_token,
            "Content-Type": "application/json",
        }

        start = time.perf_counter()
        try:
            response = await self._client.post(
                self._url,
                json=body,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            logger.warning(
                "llm_proxy_embed.timeout",
                extra={
                    "event": "llm_proxy_embed.timeout",
                    "n_texts": len(texts),
                    "timeout_seconds": self._timeout_seconds,
                    "error": type(exc).__name__,
                },
            )
            raise TransientEmbeddingError(
                upstream_status=None,
                reason="timeout",
            ) from exc

        upstream_latency_ms = int((time.perf_counter() - start) * 1000)
        status = response.status_code

        if status == 429:
            retry_after = _parse_retry_after(
                response.headers.get("Retry-After")
            )
            logger.warning(
                "llm_proxy_embed.rate_limited",
                extra={
                    "event": "llm_proxy_embed.rate_limited",
                    "n_texts": len(texts),
                    "upstream_status": status,
                    "retry_after_seconds": retry_after,
                },
            )
            raise TransientEmbeddingError(
                upstream_status=status,
                retry_after_seconds=retry_after,
                reason="rate_limited",
            )

        if status == 422:
            logger.error(
                "llm_proxy_embed.invalid_input",
                extra={
                    "event": "llm_proxy_embed.invalid_input",
                    "n_texts": len(texts),
                    "upstream_status": status,
                },
            )
            raise PermanentEmbeddingError(
                upstream_status=status,
                reason="invalid_input",
            )

        if status >= 500:
            logger.warning(
                "llm_proxy_embed.upstream_5xx",
                extra={
                    "event": "llm_proxy_embed.upstream_5xx",
                    "n_texts": len(texts),
                    "upstream_status": status,
                },
            )
            raise TransientEmbeddingError(
                upstream_status=status,
                reason=f"upstream_{status}",
            )

        if status >= 400:
            # 4xx non-429, non-422. llm-proxy does not produce other
            # 4xx codes today (see PR #18 ``error_handlers.py``), so
            # reaching here means a contract drift — fail loud.
            logger.error(
                "llm_proxy_embed.unexpected_4xx",
                extra={
                    "event": "llm_proxy_embed.unexpected_4xx",
                    "n_texts": len(texts),
                    "upstream_status": status,
                },
            )
            raise PermanentEmbeddingError(
                upstream_status=status,
                reason="unexpected_4xx",
            )

        return _parse_success(
            response=response,
            requested_count=len(texts),
            expected_dimensions=self._expected_dimensions,
            upstream_latency_ms=upstream_latency_ms,
        )


def _parse_retry_after(header: str | None) -> int | None:
    """Parse HTTP ``Retry-After`` header as an integer seconds value.

    The spec allows either a seconds integer or an HTTP-date. llm-proxy
    emits seconds (via slowapi). Anything else -> ``None`` so the
    caller's backoff policy applies a default window.
    """
    if not header:
        return None
    value = header.strip()
    try:
        return int(value)
    except ValueError:
        return None


def _parse_success(
    *,
    response: httpx.Response,
    requested_count: int,
    expected_dimensions: int,
    upstream_latency_ms: int,
) -> EmbeddingResult:
    """Extract an ``EmbeddingResult`` from a 2xx llm-proxy response.

    Strict parsing — a silently mutated envelope fails here rather
    than downstream with a confusing ``KeyError``.
    """
    try:
        payload = response.json()
    except ValueError as exc:
        raise PermanentEmbeddingError(
            upstream_status=response.status_code,
            reason="non_json_2xx",
        ) from exc

    dimensions = payload.get("dimensions")
    if dimensions != expected_dimensions:
        raise PermanentEmbeddingError(
            upstream_status=response.status_code,
            reason=f"dimension_mismatch_{dimensions}",
        )

    items = payload.get("items")
    if not isinstance(items, list) or len(items) != requested_count:
        raise PermanentEmbeddingError(
            upstream_status=response.status_code,
            reason="items_count_mismatch",
        )

    try:
        sorted_items = sorted(items, key=lambda item: item["index"])
    except (KeyError, TypeError) as exc:
        raise PermanentEmbeddingError(
            upstream_status=response.status_code,
            reason="item_missing_index",
        ) from exc

    vectors: list[list[float]] = []
    for item in sorted_items:
        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            raise PermanentEmbeddingError(
                upstream_status=response.status_code,
                reason="item_missing_embedding_list",
            )
        if len(embedding) != expected_dimensions:
            # Top-level ``dimensions`` matched but a single vector
            # length differs — shouldn't happen, but double-check
            # so a partial mutation can't smuggle a bad vector into
            # the DB.
            raise PermanentEmbeddingError(
                upstream_status=response.status_code,
                reason=f"vector_dimension_mismatch_{len(embedding)}",
            )
        vectors.append(embedding)

    model_returned = payload.get("model")
    if not isinstance(model_returned, str) or not model_returned:
        raise PermanentEmbeddingError(
            upstream_status=response.status_code,
            reason="missing_model_field",
        )

    cache_hit = bool(payload.get("cache_hit", False))

    return EmbeddingResult(
        vectors=vectors,
        model_returned=model_returned,
        cache_hit=cache_hit,
        upstream_latency_ms=upstream_latency_ms,
    )

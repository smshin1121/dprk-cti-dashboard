"""OpenAI embedding provider — PR #18 Group B (plan D3/D7/D8).

Thin wrapper over ``POST https://api.openai.com/v1/embeddings`` using
a raw ``httpx.AsyncClient``. No ``openai`` SDK dependency — the API
surface we need is small enough that owning the HTTP shape directly
is simpler than carrying a transitive version boundary.

Error taxonomy (D7 Draft v2 — mapped to the exceptions in
``errors.py``, HTTP statuses come from there):

  - ``httpx.TimeoutException``               → ``UpstreamTimeoutError`` (504)
  - Upstream response 5xx                    → ``UpstreamError`` (502)
  - Upstream response 429                    → ``UpstreamRateLimitError``
                                               (429, ``retry_after_seconds``
                                               parsed from ``Retry-After``
                                               header when present)
  - Upstream response 4xx (non-429)          → ``UpstreamError`` (502; from
                                               the caller's perspective the
                                               proxy can't repair a malformed
                                               upstream contract)

No automatic retry inside the provider. Callers own their retry
budget (plan D7).

Raw text safety (criterion #4 for Group B review): the OpenAI API
sometimes echoes the ``input`` field in error responses. This
provider's error handlers log ONLY the upstream status code and
error ``type`` / ``code`` fields from the response JSON — NEVER the
``message`` body or anything else that might quote back user input.
The log_schema layer (``log_schema.py``) enforces this by construction.
"""

from __future__ import annotations

import logging
import time

import httpx

from ..errors import UpstreamError, UpstreamRateLimitError, UpstreamTimeoutError
from ..log_schema import make_log_extra
from .base import EmbeddingProvider, ProviderResult

logger = logging.getLogger(__name__)

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """``EmbeddingProvider`` backed by the OpenAI REST API.

    Constructor takes an explicit ``httpx.AsyncClient`` so tests can
    inject ``httpx.MockTransport`` without monkey-patching module
    globals. Production wiring (Group C main.py) builds the client
    with ``timeout=httpx.Timeout(settings.timeout_seconds)``.
    """

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient,
        timeout_seconds: float,
    ) -> None:
        if not api_key.strip():
            # Defense in depth — config validator already enforces
            # this, but the provider itself should not trust caller
            # init either.
            raise ValueError("OpenAIEmbeddingProvider requires a non-empty api_key")
        self._api_key = api_key
        self._client = client
        self._timeout_seconds = timeout_seconds

    async def embed(
        self,
        texts: list[str],
        model: str,
    ) -> ProviderResult:
        """Call the OpenAI embeddings endpoint and return a
        ``ProviderResult``.

        Raises the D7 exceptions on the mapped failure paths.
        """
        request_body = {
            "input": texts,
            "model": model,
            "encoding_format": "float",
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        start = time.perf_counter()
        try:
            response = await self._client.post(
                OPENAI_EMBEDDINGS_URL,
                json=request_body,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            # Local client deadline hit — upstream never responded.
            # D7: 504 Gateway Timeout.
            logger.warning(
                "openai.embed.timeout",
                extra=make_log_extra(
                    event="openai.embed.timeout",
                    provider="openai",
                    model_requested=model,
                    n_texts=len(texts),
                    timeout_seconds=self._timeout_seconds,
                    error=type(exc).__name__,
                ),
            )
            raise UpstreamTimeoutError(timeout_seconds=self._timeout_seconds) from exc

        upstream_latency_ms = int((time.perf_counter() - start) * 1000)

        if response.status_code == 429:
            # Upstream rate-limited us. Bubble through with
            # Retry-After when present.
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            logger.warning(
                "openai.embed.rate_limited",
                extra=make_log_extra(
                    event="openai.embed.rate_limited",
                    provider="openai",
                    model_requested=model,
                    n_texts=len(texts),
                    upstream_status=429,
                    retry_after_seconds=retry_after,
                ),
            )
            raise UpstreamRateLimitError(retry_after_seconds=retry_after)

        if response.status_code >= 500:
            # Upstream 5xx — genuine provider-side failure. D7: 502.
            logger.warning(
                "openai.embed.upstream_5xx",
                extra=make_log_extra(
                    event="openai.embed.upstream_5xx",
                    provider="openai",
                    model_requested=model,
                    n_texts=len(texts),
                    upstream_status=response.status_code,
                ),
            )
            raise UpstreamError(upstream_status=response.status_code)

        if response.status_code >= 400:
            # 4xx non-429. Our request was wrong from OpenAI's POV
            # (e.g., unknown model, malformed body). From the proxy
            # caller's perspective this is still "upstream can't
            # help" — surface as 502. Never log the raw response
            # body since it may echo the request input.
            logger.warning(
                "openai.embed.upstream_4xx",
                extra=make_log_extra(
                    event="openai.embed.upstream_4xx",
                    provider="openai",
                    model_requested=model,
                    n_texts=len(texts),
                    upstream_status=response.status_code,
                ),
            )
            raise UpstreamError(upstream_status=response.status_code)

        # Happy path — parse into ProviderResult. Strict parsing so
        # a silently mutated upstream schema surfaces here, not
        # downstream.
        return _parse_success(response, texts, upstream_latency_ms)


def _parse_retry_after(header: str | None) -> int | None:
    """Interpret an HTTP ``Retry-After`` header as seconds.

    The spec allows either a seconds integer OR an HTTP-date. OpenAI
    sends seconds in practice; we fall back to ``None`` on unknown
    formats rather than guessing at a date — caller retry logic
    tolerates ``None`` (just backs off a default window).
    """
    if not header:
        return None
    value = header.strip()
    try:
        return int(value)
    except ValueError:
        return None


def _parse_success(
    response: httpx.Response,
    requested_texts: list[str],
    upstream_latency_ms: int,
) -> ProviderResult:
    """Extract ``ProviderResult`` from a 2xx OpenAI response."""
    try:
        payload = response.json()
    except ValueError as exc:
        # 2xx with a non-JSON body — OpenAI shouldn't do this, but
        # if it ever does, surface as UpstreamError so the caller
        # sees a clean 502 rather than a deserialization stack.
        raise UpstreamError(
            upstream_status=response.status_code,
            detail="upstream 2xx returned non-JSON body",
        ) from exc

    data = payload.get("data")
    if not isinstance(data, list) or len(data) != len(requested_texts):
        raise UpstreamError(
            upstream_status=response.status_code,
            detail=(
                f"upstream data array length mismatch: "
                f"got {len(data) if isinstance(data, list) else 'non-list'}, "
                f"requested {len(requested_texts)}"
            ),
        )

    # Sort by `index` so vectors[i] corresponds to requested_texts[i]
    # regardless of the order OpenAI returned them. OpenAI's docs
    # say the response preserves request order, but sorting by
    # explicit index is a cheap regression guard if that ever changes.
    try:
        sorted_data = sorted(data, key=lambda item: item["index"])
    except (KeyError, TypeError) as exc:
        raise UpstreamError(
            upstream_status=response.status_code,
            detail="upstream data item missing 'index' field",
        ) from exc

    vectors: list[list[float]] = []
    for item in sorted_data:
        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            raise UpstreamError(
                upstream_status=response.status_code,
                detail="upstream data item missing 'embedding' list",
            )
        vectors.append(embedding)

    # D8 observability: model_returned is what upstream actually
    # used. Can differ from the request's ``model`` when OpenAI
    # rolls a minor version under the same string name.
    model_returned = payload.get("model")
    if not isinstance(model_returned, str) or not model_returned:
        raise UpstreamError(
            upstream_status=response.status_code,
            detail="upstream response missing 'model' field",
        )

    usage = payload.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens", 0))
    total_tokens = int(usage.get("total_tokens", prompt_tokens))

    return ProviderResult(
        vectors=vectors,
        model_returned=model_returned,
        prompt_tokens=prompt_tokens,
        total_tokens=total_tokens,
        upstream_latency_ms=upstream_latency_ms,
    )

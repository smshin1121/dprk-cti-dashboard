"""Unit tests for ``llm_proxy.providers.openai`` — PR #18 Group B.

Four review criteria for Group B pinned here as in-commit assertions:

  1. OpenAI provider maps every D7 branch exactly: happy / 429 /
     5xx / 4xx-non-429 / timeout — each to the correct exception
     type AND the correct HTTP status code.
  2. ``model_returned`` populated from actual upstream response JSON,
     NOT copied from the request (D8 observability).
  3. ``ProviderResult`` shape identical across MockEmbeddingProvider
     and OpenAIEmbeddingProvider (Protocol compliance).
  4. Raw text content NEVER appears in log output on ANY error path
     (sentinel-canary integration sanity).
"""

from __future__ import annotations

import logging
from dataclasses import fields as dataclass_fields
from typing import Callable

import httpx
import pytest

from llm_proxy.errors import (
    UpstreamError,
    UpstreamRateLimitError,
    UpstreamTimeoutError,
)
from llm_proxy.providers.base import ProviderResult
from llm_proxy.providers.mock import MockEmbeddingProvider
from llm_proxy.providers.openai import (
    OPENAI_EMBEDDINGS_URL,
    OpenAIEmbeddingProvider,
)


# ---------------------------------------------------------------------------
# Test harness — build an OpenAIEmbeddingProvider with httpx.MockTransport
# ---------------------------------------------------------------------------


def _make_provider(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    api_key: str = "sk-test-key",
    timeout_seconds: float = 10.0,
) -> OpenAIEmbeddingProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, timeout=timeout_seconds)
    return OpenAIEmbeddingProvider(
        api_key=api_key,
        client=client,
        timeout_seconds=timeout_seconds,
    )


def _happy_response_body(
    texts: list[str],
    *,
    model_returned: str = "text-embedding-3-small",
    dim: int = 1536,
) -> dict:
    """Build an OpenAI-shaped 200 response body for ``texts``."""
    return {
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "embedding": [0.1 * (i + 1)] * dim,
                "index": i,
            }
            for i, _t in enumerate(texts)
        ],
        "model": model_returned,
        "usage": {
            "prompt_tokens": sum(max(1, len(t) // 4) for t in texts),
            "total_tokens": sum(max(1, len(t) // 4) for t in texts),
        },
    }


# ---------------------------------------------------------------------------
# Criterion #1 — error taxonomy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestD7ErrorTaxonomy:
    async def test_happy_path_returns_provider_result(self) -> None:
        texts = ["alpha", "beta"]

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == httpx.URL(OPENAI_EMBEDDINGS_URL)
            assert request.headers["Authorization"] == "Bearer sk-test-key"
            return httpx.Response(200, json=_happy_response_body(texts))

        provider = _make_provider(handler)
        result = await provider.embed(texts, model="text-embedding-3-small")
        assert isinstance(result, ProviderResult)
        assert len(result.vectors) == 2
        assert all(len(v) == 1536 for v in result.vectors)

    async def test_upstream_timeout_maps_to_504(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("simulated deadline")

        provider = _make_provider(handler, timeout_seconds=7.5)
        with pytest.raises(UpstreamTimeoutError) as exc_info:
            await provider.embed(["x"], model="m")
        # D7 Draft v2: 504 distinct from 502.
        assert exc_info.value.status_code == 504
        assert exc_info.value.timeout_seconds == 7.5
        assert exc_info.value.retryable is True

    @pytest.mark.parametrize("upstream_status", [500, 502, 503, 504])
    async def test_upstream_5xx_maps_to_502_upstream_error(
        self, upstream_status: int
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(upstream_status, json={"error": {"message": "oops"}})

        provider = _make_provider(handler)
        with pytest.raises(UpstreamError) as exc_info:
            await provider.embed(["x"], model="m")
        # Proxy-facing status is always 502 regardless of which
        # specific 5xx upstream sent.
        assert exc_info.value.status_code == 502
        assert exc_info.value.upstream_status == upstream_status
        assert exc_info.value.retryable is True
        # NOT UpstreamTimeoutError (distinct branch).
        assert not isinstance(exc_info.value, UpstreamTimeoutError)

    async def test_upstream_429_maps_to_rate_limit_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                json={"error": {"message": "rate limit"}},
                headers={"Retry-After": "30"},
            )

        provider = _make_provider(handler)
        with pytest.raises(UpstreamRateLimitError) as exc_info:
            await provider.embed(["x"], model="m")
        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after_seconds == 30
        assert exc_info.value.retryable is True

    async def test_upstream_429_without_retry_after_header(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": {"message": "rate limit"}})

        provider = _make_provider(handler)
        with pytest.raises(UpstreamRateLimitError) as exc_info:
            await provider.embed(["x"], model="m")
        # None fallback — callers tolerate it by backing off a default.
        assert exc_info.value.retry_after_seconds is None

    async def test_upstream_429_with_malformed_retry_after(self) -> None:
        """HTTP-date format or other non-integer — fall back to None
        rather than guessing (we don't parse date strings)."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                json={"error": {"message": "x"}},
                headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
            )

        provider = _make_provider(handler)
        with pytest.raises(UpstreamRateLimitError) as exc_info:
            await provider.embed(["x"], model="m")
        assert exc_info.value.retry_after_seconds is None

    @pytest.mark.parametrize("upstream_status", [400, 401, 403, 404, 422])
    async def test_upstream_4xx_non_429_maps_to_502(
        self, upstream_status: int
    ) -> None:
        """4xx-non-429 means our request was wrong from upstream's
        POV — from the proxy caller's perspective upstream can't
        help, so we surface as 502 rather than echoing the 4xx."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                upstream_status,
                json={"error": {"message": "unknown model", "type": "invalid_request"}},
            )

        provider = _make_provider(handler)
        with pytest.raises(UpstreamError) as exc_info:
            await provider.embed(["x"], model="m")
        assert exc_info.value.status_code == 502
        assert exc_info.value.upstream_status == upstream_status

    async def test_upstream_2xx_with_non_json_body_maps_to_upstream_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                text="not json at all",
                headers={"Content-Type": "text/plain"},
            )

        provider = _make_provider(handler)
        with pytest.raises(UpstreamError):
            await provider.embed(["x"], model="m")


# ---------------------------------------------------------------------------
# Criterion #2 — model_returned wires to actual response parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestModelReturnedObservability:
    async def test_model_returned_comes_from_response_not_request(self) -> None:
        """If upstream responds with a more specific version string,
        we return that — not the model string the caller requested."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_happy_response_body(
                    ["x"],
                    model_returned="text-embedding-3-small-2024-02-01",
                ),
            )

        provider = _make_provider(handler)
        result = await provider.embed(["x"], model="text-embedding-3-small")
        # Request was short name; response had versioned name. The
        # returned value MUST be the versioned one so a future cache-
        # flush script can target upstream drift forensically.
        assert result.model_returned == "text-embedding-3-small-2024-02-01"

    async def test_missing_model_field_raises_upstream_error(self) -> None:
        """The D8 model_returned field is load-bearing; missing it
        is a contract violation, NOT a silent default."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = _happy_response_body(["x"])
            del body["model"]
            return httpx.Response(200, json=body)

        provider = _make_provider(handler)
        with pytest.raises(UpstreamError, match="model"):
            await provider.embed(["x"], model="m")

    async def test_model_returned_matches_request_when_no_drift(self) -> None:
        """Normal happy case — request and response agree."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_happy_response_body(["x"], model_returned="m"),
            )

        provider = _make_provider(handler)
        result = await provider.embed(["x"], model="m")
        assert result.model_returned == "m"


# ---------------------------------------------------------------------------
# Criterion #3 — ProviderResult shape consistency across Mock/OpenAI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProviderResultShapeConsistency:
    """Mock and OpenAI providers return the SAME dataclass type
    with the SAME field set. Protocol compliance — Group C route
    code must be able to consume either interchangeably."""

    async def test_both_providers_return_same_dataclass(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_happy_response_body(["x"]))

        openai = _make_provider(handler)
        mock = MockEmbeddingProvider()

        r_openai = await openai.embed(["x"], model="m")
        r_mock = await mock.embed(["x"], model="m")

        # Exact same dataclass type — not just duck-typed similar.
        assert type(r_openai) is ProviderResult
        assert type(r_mock) is ProviderResult

    async def test_both_providers_return_same_field_set(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_happy_response_body(["x"]))

        openai = _make_provider(handler)
        mock = MockEmbeddingProvider()

        r_openai = await openai.embed(["x"], model="m")
        r_mock = await mock.embed(["x"], model="m")

        openai_fields = {f.name for f in dataclass_fields(r_openai)}
        mock_fields = {f.name for f in dataclass_fields(r_mock)}
        # Field-name identity — if a future ProviderResult split
        # adds OpenAI-only fields (say, tokens_per_model), this
        # test flips red and forces the split to be deliberate.
        assert openai_fields == mock_fields
        assert openai_fields == {
            "vectors",
            "model_returned",
            "prompt_tokens",
            "total_tokens",
            "upstream_latency_ms",
        }

    async def test_both_vectors_are_1536_dim(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_happy_response_body(["x"]))

        openai = _make_provider(handler)
        mock = MockEmbeddingProvider()

        r_openai = await openai.embed(["x"], model="m")
        r_mock = await mock.embed(["x"], model="m")
        assert len(r_openai.vectors[0]) == 1536
        assert len(r_mock.vectors[0]) == 1536


# ---------------------------------------------------------------------------
# Criterion #4 — raw text never in logs, even on error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNoRawTextInLogs:
    """D8 LOCKED invariant enforced on EVERY error branch.

    Each error path's `logger.warning(...)` call routes through
    `make_log_extra(...)` which rejects `texts` / `text` / etc.
    But we also pin the end-to-end behavior: a sentinel canary in
    the request MUST NOT appear in captured log output on any
    error path.
    """

    SENTINEL = "SENTINEL-CANARY-OPENAI-PR18-0xF00D"

    async def test_no_sentinel_in_logs_on_timeout_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("simulated")

        provider = _make_provider(handler)
        caplog.set_level(logging.DEBUG)  # Widest net possible.
        with pytest.raises(UpstreamTimeoutError):
            await provider.embed([self.SENTINEL], model="m")

        captured = "\n".join(r.getMessage() for r in caplog.records) + "\n" + "\n".join(
            repr(r.__dict__) for r in caplog.records
        )
        assert self.SENTINEL not in captured, (
            "Sentinel canary appeared in log output on timeout path — "
            "a raw-text leak has regressed"
        )

    async def test_no_sentinel_in_logs_on_upstream_5xx_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            # Realistic worst case: upstream echoes the input in
            # its error body (OpenAI has been observed to do this).
            return httpx.Response(
                503,
                json={"error": {"message": f"failed on input: {self.SENTINEL}"}},
            )

        provider = _make_provider(handler)
        caplog.set_level(logging.DEBUG)
        with pytest.raises(UpstreamError):
            await provider.embed([self.SENTINEL], model="m")

        captured = "\n".join(r.getMessage() for r in caplog.records) + "\n" + "\n".join(
            repr(r.__dict__) for r in caplog.records
        )
        assert self.SENTINEL not in captured

    async def test_no_sentinel_in_logs_on_429_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                json={"error": {"message": f"rate limit on {self.SENTINEL}"}},
                headers={"Retry-After": "5"},
            )

        provider = _make_provider(handler)
        caplog.set_level(logging.DEBUG)
        with pytest.raises(UpstreamRateLimitError):
            await provider.embed([self.SENTINEL], model="m")

        captured = "\n".join(r.getMessage() for r in caplog.records) + "\n" + "\n".join(
            repr(r.__dict__) for r in caplog.records
        )
        assert self.SENTINEL not in captured

    async def test_no_sentinel_in_logs_on_4xx_path(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": f"invalid input {self.SENTINEL}",
                        "type": "invalid_request",
                    }
                },
            )

        provider = _make_provider(handler)
        caplog.set_level(logging.DEBUG)
        with pytest.raises(UpstreamError):
            await provider.embed([self.SENTINEL], model="m")

        captured = "\n".join(r.getMessage() for r in caplog.records) + "\n" + "\n".join(
            repr(r.__dict__) for r in caplog.records
        )
        assert self.SENTINEL not in captured


# ---------------------------------------------------------------------------
# Edge cases — request construction + constructor defense
# ---------------------------------------------------------------------------


class TestConstructorDefense:
    def test_empty_api_key_rejected(self) -> None:
        client = httpx.AsyncClient()
        with pytest.raises(ValueError, match="api_key"):
            OpenAIEmbeddingProvider(
                api_key="",
                client=client,
                timeout_seconds=10.0,
            )

    def test_whitespace_api_key_rejected(self) -> None:
        client = httpx.AsyncClient()
        with pytest.raises(ValueError, match="api_key"):
            OpenAIEmbeddingProvider(
                api_key="   ",
                client=client,
                timeout_seconds=10.0,
            )


@pytest.mark.asyncio
class TestRequestConstruction:
    async def test_sends_bearer_token_and_expected_body(self) -> None:
        captured_request: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_request["url"] = str(request.url)
            captured_request["auth"] = request.headers.get("Authorization")
            captured_request["content_type"] = request.headers.get("Content-Type")
            import json as _json

            captured_request["body"] = _json.loads(request.content)
            return httpx.Response(200, json=_happy_response_body(["hello"]))

        provider = _make_provider(handler, api_key="sk-live")
        await provider.embed(["hello"], model="text-embedding-3-small")

        assert captured_request["url"] == OPENAI_EMBEDDINGS_URL
        assert captured_request["auth"] == "Bearer sk-live"
        assert captured_request["content_type"] == "application/json"
        assert captured_request["body"] == {
            "input": ["hello"],
            "model": "text-embedding-3-small",
            "encoding_format": "float",
        }

    async def test_batch_preserves_index_order(self) -> None:
        """Upstream returns items possibly out-of-order; provider
        sorts by `index` so vectors[i] aligns with requested
        texts[i]. Regression guard against a silent ordering
        assumption."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = _happy_response_body(["alpha", "beta", "gamma"])
            # Shuffle the upstream response order — reversed.
            body["data"] = list(reversed(body["data"]))
            return httpx.Response(200, json=body)

        provider = _make_provider(handler)
        result = await provider.embed(["alpha", "beta", "gamma"], model="m")
        # vectors[0] must correspond to index=0 (alpha) not to the
        # last item in the shuffled upstream response.
        # The first-index entry in _happy_response_body has
        # embedding = [0.1] * 1536, index=1 has [0.2] * 1536, etc.
        assert result.vectors[0][0] == pytest.approx(0.1)
        assert result.vectors[1][0] == pytest.approx(0.2)
        assert result.vectors[2][0] == pytest.approx(0.3)

    async def test_upstream_returns_mismatched_item_count_raises(self) -> None:
        """If upstream returns 2 items when we asked for 3, surface
        as UpstreamError — the caller's index mapping would be
        broken if we tried to patch around it."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = _happy_response_body(["a", "b", "c"])
            body["data"] = body["data"][:2]
            return httpx.Response(200, json=body)

        provider = _make_provider(handler)
        with pytest.raises(UpstreamError, match="length mismatch"):
            await provider.embed(["a", "b", "c"], model="m")


@pytest.mark.asyncio
class TestUsageExtraction:
    async def test_usage_fields_parsed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = _happy_response_body(["hello world"])
            body["usage"] = {"prompt_tokens": 3, "total_tokens": 4}
            return httpx.Response(200, json=body)

        provider = _make_provider(handler)
        result = await provider.embed(["hello world"], model="m")
        assert result.prompt_tokens == 3
        assert result.total_tokens == 4

    async def test_missing_usage_falls_back_to_zero(self) -> None:
        """OpenAI always returns usage in practice, but be
        defensive — missing usage should not crash the request."""

        def handler(request: httpx.Request) -> httpx.Response:
            body = _happy_response_body(["x"])
            del body["usage"]
            return httpx.Response(200, json=body)

        provider = _make_provider(handler)
        result = await provider.embed(["x"], model="m")
        assert result.prompt_tokens == 0
        assert result.total_tokens == 0

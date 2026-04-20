"""Tests for api.embedding_client — PR #19a Group B (api-side).

Mirror of ``services/worker/tests/unit/test_embedding_client.py``.
Both services own their own embedding client — the duplication is
intentional per plan §9.1 lock (service-local, not shared).

Every llm-proxy status class from the D5/D9 lock is exercised end-
to-end via ``httpx.MockTransport`` so the api side of the embedding
contract is pinned without a live llm-proxy.

Layout:

  - TestConstruction: constructor guards (empty base_url / token).
  - TestHappyPath: 200 + 1-text / 3-text / cache_hit / model override.
  - TestTransientFailures: 429 (with + without Retry-After),
    502 / 503 / 504, timeout.
  - TestPermanentFailures: 422, 4xx non-429-non-422, dimension
    mismatch (top-level + per-vector), items-count mismatch,
    malformed JSON, missing fields.
  - TestAuthHeader: ``X-Internal-Token`` wired on every request.
  - TestNoRawTextLog: sentinel canary — no raw input text escapes
    into log output.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from api.embedding_client import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingResult,
    LlmProxyEmbeddingClient,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)


BASE_URL = "http://llm-proxy.test"
TOKEN = "test-internal-token"
SAMPLE_TEXT = "Lazarus targets SK crypto exchanges"
SAMPLE_TEXTS_3 = [
    "Lazarus targets SK crypto exchanges",
    "BlueNoroff phishing campaign observed",
    "APT37 watering-hole attack on think tanks",
]
VECTOR_1536 = [0.0] * DEFAULT_EMBEDDING_DIMENSIONS


def _mock_client(handler) -> httpx.AsyncClient:  # noqa: ANN001
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _build_client(client: httpx.AsyncClient) -> LlmProxyEmbeddingClient:
    return LlmProxyEmbeddingClient(
        base_url=BASE_URL,
        internal_token=TOKEN,
        client=client,
        timeout_seconds=5.0,
    )


def _success_payload(
    texts: list[str],
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    cache_hit: bool = False,
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
    vector_length: int | None = None,
) -> dict[str, object]:
    vlen = dimensions if vector_length is None else vector_length
    return {
        "provider": "mock",
        "model": model,
        "dimensions": dimensions,
        "items": [
            {"index": i, "embedding": [float(i)] * vlen}
            for i in range(len(texts))
        ],
        "usage": {"prompt_tokens": 3 * len(texts), "total_tokens": 3 * len(texts)},
        "latency_ms": 7,
        "cache_hit": cache_hit,
    }


# ---------------------------------------------------------------------------
# TestConstruction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_empty_base_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty base_url"):
            LlmProxyEmbeddingClient(
                base_url="",
                internal_token=TOKEN,
                client=_mock_client(lambda _r: httpx.Response(200)),
                timeout_seconds=5.0,
            )

    def test_whitespace_base_url_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty base_url"):
            LlmProxyEmbeddingClient(
                base_url="   ",
                internal_token=TOKEN,
                client=_mock_client(lambda _r: httpx.Response(200)),
                timeout_seconds=5.0,
            )

    def test_empty_internal_token_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty internal_token"):
            LlmProxyEmbeddingClient(
                base_url=BASE_URL,
                internal_token="",
                client=_mock_client(lambda _r: httpx.Response(200)),
                timeout_seconds=5.0,
            )

    def test_base_url_trailing_slash_tolerated(self) -> None:
        seen: dict[str, str] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return httpx.Response(
                200,
                json=_success_payload([SAMPLE_TEXT]),
            )

        client = LlmProxyEmbeddingClient(
            base_url=BASE_URL + "/",
            internal_token=TOKEN,
            client=_mock_client(handler),
            timeout_seconds=5.0,
        )
        # URL must end in /api/v1/embedding exactly once, no double slash.
        assert client._url == f"{BASE_URL}/api/v1/embedding"


# ---------------------------------------------------------------------------
# TestHappyPath
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_single_text(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_success_payload([SAMPLE_TEXT]),
            )

        client = _build_client(_mock_client(handler))
        result = await client.embed([SAMPLE_TEXT])

        assert isinstance(result, EmbeddingResult)
        assert len(result.vectors) == 1
        assert len(result.vectors[0]) == DEFAULT_EMBEDDING_DIMENSIONS
        assert result.model_returned == DEFAULT_EMBEDDING_MODEL
        assert result.cache_hit is False
        assert result.upstream_latency_ms >= 0

    async def test_batch_of_three_ordered_by_index(self) -> None:
        # Return items in REVERSE order to prove _parse_success sorts by index.
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = _success_payload(SAMPLE_TEXTS_3)
            payload["items"] = list(reversed(payload["items"]))  # type: ignore[arg-type]
            return httpx.Response(200, json=payload)

        client = _build_client(_mock_client(handler))
        result = await client.embed(SAMPLE_TEXTS_3)

        assert len(result.vectors) == 3
        # _success_payload fills vector i with [float(i)] * N. After
        # sorting-by-index we should see i=0,1,2 in order.
        for i, vector in enumerate(result.vectors):
            assert vector[0] == float(i)

    async def test_cache_hit_flag_preserved(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_success_payload([SAMPLE_TEXT], cache_hit=True),
            )

        client = _build_client(_mock_client(handler))
        result = await client.embed([SAMPLE_TEXT])
        assert result.cache_hit is True

    async def test_model_override_forwarded(self) -> None:
        seen: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            body = request.content.decode("utf-8")
            seen["body"] = body
            return httpx.Response(
                200,
                json=_success_payload(
                    [SAMPLE_TEXT], model="text-embedding-3-large"
                ),
            )

        client = _build_client(_mock_client(handler))
        result = await client.embed(
            [SAMPLE_TEXT], model="text-embedding-3-large"
        )

        assert "text-embedding-3-large" in str(seen["body"])
        assert result.model_returned == "text-embedding-3-large"


# ---------------------------------------------------------------------------
# TestTransientFailures
# ---------------------------------------------------------------------------


class TestTransientFailures:
    async def test_429_with_retry_after(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                headers={"Retry-After": "30"},
                json={
                    "error": "rate_limit_exceeded",
                    "message": "slow down",
                    "retry_after_seconds": 30,
                },
            )

        client = _build_client(_mock_client(handler))
        with pytest.raises(TransientEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert exc_info.value.upstream_status == 429
        assert exc_info.value.retry_after_seconds == 30
        assert exc_info.value.reason == "rate_limited"

    async def test_429_without_retry_after(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                json={"error": "rate_limit_exceeded", "message": "slow down"},
            )

        client = _build_client(_mock_client(handler))
        with pytest.raises(TransientEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert exc_info.value.retry_after_seconds is None

    async def test_429_non_integer_retry_after_falls_back_to_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                headers={"Retry-After": "Tue, 15 Apr 2026 10:00:00 GMT"},
                json={"error": "rate_limit_exceeded"},
            )

        client = _build_client(_mock_client(handler))
        with pytest.raises(TransientEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert exc_info.value.retry_after_seconds is None

    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    async def test_upstream_5xx_is_transient(self, status: int) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"detail": "upstream failure"})

        client = _build_client(_mock_client(handler))
        with pytest.raises(TransientEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert exc_info.value.upstream_status == status
        assert exc_info.value.reason == f"upstream_{status}"

    async def test_timeout_is_transient(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("deadline hit", request=request)

        client = _build_client(_mock_client(handler))
        with pytest.raises(TransientEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert exc_info.value.upstream_status is None
        assert exc_info.value.reason == "timeout"
        assert exc_info.value.retry_after_seconds is None


# ---------------------------------------------------------------------------
# TestPermanentFailures
# ---------------------------------------------------------------------------


class TestPermanentFailures:
    async def test_422_is_permanent(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                json={"detail": "empty text at index 0", "retryable": False},
            )

        client = _build_client(_mock_client(handler))
        with pytest.raises(PermanentEmbeddingError) as exc_info:
            await client.embed([""])

        assert exc_info.value.upstream_status == 422
        assert exc_info.value.reason == "invalid_input"

    @pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
    async def test_unexpected_4xx_is_permanent(self, status: int) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"detail": "unexpected"})

        client = _build_client(_mock_client(handler))
        with pytest.raises(PermanentEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert exc_info.value.upstream_status == status
        assert exc_info.value.reason == "unexpected_4xx"

    async def test_dimension_mismatch_is_permanent(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_success_payload([SAMPLE_TEXT], dimensions=512),
            )

        client = _build_client(_mock_client(handler))
        with pytest.raises(PermanentEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert exc_info.value.reason == "dimension_mismatch_512"

    async def test_per_vector_length_mismatch_is_permanent(self) -> None:
        # Top-level ``dimensions`` reports 1536 but the embedding
        # vector is 512 long — double-check catches the partial
        # mutation.
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = _success_payload(
                [SAMPLE_TEXT],
                dimensions=DEFAULT_EMBEDDING_DIMENSIONS,
                vector_length=512,
            )
            return httpx.Response(200, json=payload)

        client = _build_client(_mock_client(handler))
        with pytest.raises(PermanentEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert "vector_dimension_mismatch_512" == exc_info.value.reason

    async def test_items_count_mismatch_is_permanent(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = _success_payload(SAMPLE_TEXTS_3)
            payload["items"] = payload["items"][:2]  # type: ignore[index]
            return httpx.Response(200, json=payload)

        client = _build_client(_mock_client(handler))
        with pytest.raises(PermanentEmbeddingError) as exc_info:
            await client.embed(SAMPLE_TEXTS_3)

        assert exc_info.value.reason == "items_count_mismatch"

    async def test_non_json_2xx_is_permanent(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json")

        client = _build_client(_mock_client(handler))
        with pytest.raises(PermanentEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert exc_info.value.reason == "non_json_2xx"

    async def test_missing_model_field_is_permanent(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = _success_payload([SAMPLE_TEXT])
            del payload["model"]
            return httpx.Response(200, json=payload)

        client = _build_client(_mock_client(handler))
        with pytest.raises(PermanentEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert exc_info.value.reason == "missing_model_field"

    async def test_item_missing_index_is_permanent(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = _success_payload([SAMPLE_TEXT])
            del payload["items"][0]["index"]  # type: ignore[index]
            return httpx.Response(200, json=payload)

        client = _build_client(_mock_client(handler))
        with pytest.raises(PermanentEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert exc_info.value.reason == "item_missing_index"

    async def test_item_missing_embedding_list_is_permanent(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = _success_payload([SAMPLE_TEXT])
            payload["items"][0]["embedding"] = "not-a-list"  # type: ignore[index]
            return httpx.Response(200, json=payload)

        client = _build_client(_mock_client(handler))
        with pytest.raises(PermanentEmbeddingError) as exc_info:
            await client.embed([SAMPLE_TEXT])

        assert exc_info.value.reason == "item_missing_embedding_list"


# ---------------------------------------------------------------------------
# TestAuthHeader
# ---------------------------------------------------------------------------


class TestAuthHeader:
    async def test_internal_token_header_sent(self) -> None:
        seen: dict[str, str] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            seen["token"] = request.headers.get("X-Internal-Token", "")
            return httpx.Response(
                200,
                json=_success_payload([SAMPLE_TEXT]),
            )

        client = _build_client(_mock_client(handler))
        await client.embed([SAMPLE_TEXT])
        assert seen["token"] == TOKEN

    async def test_content_type_json(self) -> None:
        seen: dict[str, str] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            seen["ct"] = request.headers.get("Content-Type", "")
            return httpx.Response(
                200,
                json=_success_payload([SAMPLE_TEXT]),
            )

        client = _build_client(_mock_client(handler))
        await client.embed([SAMPLE_TEXT])
        assert seen["ct"].startswith("application/json")


# ---------------------------------------------------------------------------
# TestNoRawTextLog
# ---------------------------------------------------------------------------
#
# Sentinel canary — a single capturable attribute concatenation
# across every log record the client produces, asserted to NOT
# contain the sentinel even on error paths where upstream responses
# deliberately echo it back. Mirrors the llm-proxy log_schema
# test pattern (PR #18 ``TestNoRawTextLog``).


SENTINEL = "CANARY-API-EMBED-PR19A-ZZ9"


def _all_record_text(records: list[logging.LogRecord]) -> str:
    chunks: list[str] = []
    for record in records:
        chunks.append(record.getMessage())
        chunks.append(repr(record.args))
        chunks.append(repr(record.__dict__))
    return "\n".join(chunks)


class TestNoRawTextLog:
    async def test_happy_path_does_not_log_sentinel(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=_success_payload([SENTINEL]),
            )

        caplog.set_level(logging.DEBUG, logger="worker.bootstrap.embedding_client")
        client = _build_client(_mock_client(handler))
        await client.embed([SENTINEL])

        assert SENTINEL not in _all_record_text(caplog.records)

    async def test_429_body_echo_does_not_log_sentinel(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Upstream 429 body deliberately echoes the sentinel — the
        # client must not read body into log fields.
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                headers={"Retry-After": "5"},
                json={
                    "error": "rate_limit_exceeded",
                    "message": f"slow down: {SENTINEL}",
                    "retry_after_seconds": 5,
                },
            )

        caplog.set_level(logging.DEBUG, logger="worker.bootstrap.embedding_client")
        client = _build_client(_mock_client(handler))
        with pytest.raises(TransientEmbeddingError):
            await client.embed([SENTINEL])

        assert SENTINEL not in _all_record_text(caplog.records)

    async def test_5xx_body_echo_does_not_log_sentinel(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                502,
                json={"detail": f"upstream echo: {SENTINEL}"},
            )

        caplog.set_level(logging.DEBUG, logger="worker.bootstrap.embedding_client")
        client = _build_client(_mock_client(handler))
        with pytest.raises(TransientEmbeddingError):
            await client.embed([SENTINEL])

        assert SENTINEL not in _all_record_text(caplog.records)

    async def test_422_body_echo_does_not_log_sentinel(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                json={
                    "detail": f"empty text near: {SENTINEL}",
                    "retryable": False,
                },
            )

        caplog.set_level(logging.DEBUG, logger="worker.bootstrap.embedding_client")
        client = _build_client(_mock_client(handler))
        with pytest.raises(PermanentEmbeddingError):
            await client.embed([SENTINEL])

        assert SENTINEL not in _all_record_text(caplog.records)

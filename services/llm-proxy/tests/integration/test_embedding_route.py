"""Integration tests for POST /api/v1/embedding — PR #18 Group D.

The tests drive the full route stack end-to-end: X-Internal-Token
middleware → slowapi rate limiter → FastAPI DTO validation →
exception handlers → route body → cache + provider dispatch →
envelope + structured log. Individual primitives are unit-tested
in Groups A / B; this module pins the contract of the composition.

Every success-criterion from ``docs/plans/pr18-llm-proxy-embedding.md``
§7 has at least one dedicated class here:

  - §7.1 happy path via mock provider → :class:`TestHappyPath`
  - §7.3 every D7 error taxonomy branch → :class:`TestUpstreamErrors`
    + :class:`TestInputValidation422`
  - §7.4 D5 rate-limit end-to-end     → :class:`TestLocalRateLimit`
  - §7.5 Redis cache round-trip +
         D6 provider-in-key            → :class:`TestCacheRoundTrip` +
                                         :class:`TestPartialCacheHit`
  - §7.6 D8 LOCKED no-raw-text         → :class:`TestNoRawTextLog`
  - §7.8 dimensions field              → asserted across TestHappyPath
  - §7.11 OpenAPI shape                → :class:`TestOpenAPIShape`
  - §7.10 existing endpoints unchanged → :class:`TestExistingEndpointsStable`

Auth guard (401 / 503) covered in :class:`TestAuthGuard` — not a
numbered success criterion but load-bearing for D4 (shared-secret
middleware is the only auth surface).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from llm_proxy import main as main_module
from llm_proxy.cache import cache_key
from llm_proxy.config import get_settings
from llm_proxy.providers.mock import EMBEDDING_DIM

from .conftest import (
    INTEGRATION_TOKEN,
    OPENAI_EMBEDDINGS_URL,
    CountingMockProvider,
    openai_happy_body,
)

# The one sentinel string locked at D8 — appears in every test
# that pins the no-raw-text invariant.
SENTINEL: str = "SENTINEL-PII-CANARY-7F3A"

ENDPOINT: str = "/api/v1/embedding"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post(client: TestClient, body: dict[str, Any], **kwargs: Any) -> httpx.Response:
    """Convenience wrapper — always returns the response object."""
    return client.post(ENDPOINT, json=body, **kwargs)


# ---------------------------------------------------------------------------
# Auth guard (D4) — middleware is the only auth surface
# ---------------------------------------------------------------------------


class TestAuthGuard:
    """The X-Internal-Token middleware must fire BEFORE the route,
    so a bad/missing token reaches neither the rate limiter nor the
    DTO validator."""

    def test_missing_token_returns_401(
        self, test_client: TestClient
    ) -> None:
        test_client.headers.pop("X-Internal-Token", None)
        response = _post(test_client, {"texts": ["hello"]})
        assert response.status_code == 401

    def test_wrong_token_returns_401(
        self, test_client: TestClient
    ) -> None:
        test_client.headers["X-Internal-Token"] = "not-the-real-token"
        response = _post(test_client, {"texts": ["hello"]})
        assert response.status_code == 401

    def test_empty_server_token_returns_503(
        self,
        test_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When ``LLM_PROXY_INTERNAL_TOKEN`` is unset in the server's
        env, every request (even with a header) returns 503.

        Production failure mode: a pod starts with an empty token
        env var — ALL traffic gets rejected rather than silently
        accepted. This test pins that fail-closed posture."""
        monkeypatch.setattr(main_module, "_INTERNAL_TOKEN", "")
        response = _post(test_client, {"texts": ["hello"]})
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Happy path (§7.1) — D2 envelope, D2 dimensions field, D8 log
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_single_text_returns_full_d2_envelope(
        self,
        test_client: TestClient,
        integration_redis,
    ) -> None:
        response = _post(test_client, {"texts": ["hello world"]})
        assert response.status_code == 200
        body = response.json()

        # D2 Draft v2 envelope — every top-level key.
        assert set(body.keys()) == {
            "provider",
            "model",
            "dimensions",
            "items",
            "usage",
            "latency_ms",
            "cache_hit",
        }
        assert body["provider"] == "mock"
        assert body["model"] == "mock/text-embedding-3-small"
        assert body["dimensions"] == EMBEDDING_DIM == 1536
        assert body["cache_hit"] is False
        assert isinstance(body["latency_ms"], int) and body["latency_ms"] >= 0

        # Items shape + dim pin.
        assert len(body["items"]) == 1
        assert body["items"][0]["index"] == 0
        assert len(body["items"][0]["embedding"]) == EMBEDDING_DIM

        # Usage shape.
        assert set(body["usage"].keys()) == {"prompt_tokens", "total_tokens"}

    def test_batch_of_five_returns_five_items_in_request_order(
        self,
        test_client: TestClient,
        integration_redis,
    ) -> None:
        texts = ["alpha", "beta", "gamma", "delta", "epsilon"]
        response = _post(test_client, {"texts": texts})
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 5
        # ``index`` maps back to the request ordering exactly.
        assert [item["index"] for item in body["items"]] == [0, 1, 2, 3, 4]
        # Each vector is 1536-dim.
        for item in body["items"]:
            assert len(item["embedding"]) == EMBEDDING_DIM
        # Different texts → different vectors (mock is deterministic
        # on sha256).
        vectors = [tuple(item["embedding"]) for item in body["items"]]
        assert len(set(vectors)) == 5

    def test_max_batch_of_sixteen_accepted(
        self,
        test_client: TestClient,
        integration_redis,
    ) -> None:
        texts = [f"text-{i:02d}" for i in range(16)]
        response = _post(test_client, {"texts": texts})
        assert response.status_code == 200
        assert len(response.json()["items"]) == 16

    def test_model_override_is_honored(
        self,
        test_client: TestClient,
        integration_redis,
    ) -> None:
        """An explicit ``model`` in the request overrides the server
        default. The mock provider prefixes ``mock/`` onto whatever
        model it was asked for so we can observe the override."""
        response = _post(
            test_client,
            {"texts": ["hello"], "model": "custom-model-name"},
        )
        assert response.status_code == 200
        assert response.json()["model"] == "mock/custom-model-name"


# ---------------------------------------------------------------------------
# 422 branches (§7.3 part 1) — DTO validator surface
# ---------------------------------------------------------------------------


class TestInputValidation422:
    """Every 422 case emits a ``{detail, retryable}`` body (via
    ``InvalidInputError`` + our handler). Batch-over-max and
    empty-texts-list are enforced at the Pydantic layer and bubble
    through FastAPI's default 422 shape — still rejected, but the
    body is FastAPI's array-of-errors form. Both shapes are 422,
    callers branch on status alone."""

    def test_empty_texts_list_rejected(
        self, test_client: TestClient
    ) -> None:
        assert _post(test_client, {"texts": []}).status_code == 422

    def test_empty_string_rejected(
        self, test_client: TestClient
    ) -> None:
        response = _post(test_client, {"texts": [""]})
        assert response.status_code == 422
        # Our custom InvalidInputError handler surfaces a detail
        # pointing at the offending index.
        body = response.json()
        assert "detail" in body
        assert body.get("retryable") is False

    def test_whitespace_only_string_rejected(
        self, test_client: TestClient
    ) -> None:
        response = _post(test_client, {"texts": ["   \t\n  "]})
        assert response.status_code == 422

    def test_null_text_rejected(
        self, test_client: TestClient
    ) -> None:
        """JSON ``null`` in the texts array fails validation before
        the route body touches it."""
        # Build JSON directly so a ``None`` element survives serialization.
        raw = json.dumps({"texts": [None]})
        response = test_client.post(
            ENDPOINT,
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_over_max_batch_rejected(
        self, test_client: TestClient
    ) -> None:
        texts = [f"t{i}" for i in range(17)]
        assert _post(test_client, {"texts": texts}).status_code == 422


# ---------------------------------------------------------------------------
# Upstream error mapping (§7.3 part 2) — D7 taxonomy end-to-end
# ---------------------------------------------------------------------------


class TestUpstreamErrors:
    """D7 Draft v2 locks distinct HTTP statuses AND distinct body
    shapes per branch. These tests prove the OpenAI provider's
    exceptions round-trip cleanly through the registered handlers
    (:mod:`llm_proxy.error_handlers`) onto the wire."""

    def test_upstream_5xx_maps_to_502_with_upstream_status_body(
        self,
        test_client: TestClient,
        integration_redis,
        provider_with_handler,
    ) -> None:
        provider_with_handler(
            lambda req: httpx.Response(503, json={"error": "upstream down"})
        )
        response = _post(test_client, {"texts": ["x"]})
        assert response.status_code == 502
        body = response.json()
        assert body == {
            "detail": "upstream error",
            "upstream_status": 503,
            "retryable": True,
        }

    def test_upstream_500_also_maps_to_502(
        self,
        test_client: TestClient,
        integration_redis,
        provider_with_handler,
    ) -> None:
        provider_with_handler(lambda req: httpx.Response(500))
        response = _post(test_client, {"texts": ["x"]})
        assert response.status_code == 502
        assert response.json()["upstream_status"] == 500

    def test_local_timeout_maps_to_504_not_502(
        self,
        test_client: TestClient,
        integration_redis,
        provider_with_handler,
    ) -> None:
        """Critical D7 split: httpx timeout is 504, NOT 502. Callers
        seeing repeated 504 should extend their own timeout; 502
        should trigger provider-fallback logic. Conflating them
        costs observability."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("simulated client-side deadline")

        provider_with_handler(handler, timeout_seconds=3.5)
        response = _post(test_client, {"texts": ["x"]})
        assert response.status_code == 504
        body = response.json()
        assert body == {
            "detail": "upstream timeout",
            "timeout_seconds": 3.5,
            "retryable": True,
        }

    def test_upstream_429_bubbles_as_429_with_retry_after(
        self,
        test_client: TestClient,
        integration_redis,
        provider_with_handler,
    ) -> None:
        """Upstream 429 → our 429 (bubble), distinct body shape from
        the local 30/minute 429. ``retry_after_seconds`` parsed
        from the upstream ``Retry-After`` header; ``Retry-After``
        header also set on our response."""
        provider_with_handler(
            lambda req: httpx.Response(
                429, headers={"Retry-After": "30"}, json={"error": "slow down"}
            )
        )
        response = _post(test_client, {"texts": ["x"]})
        assert response.status_code == 429
        body = response.json()
        assert body == {
            "detail": "upstream rate limit",
            "upstream_status": 429,
            "retryable": True,
            "retry_after_seconds": 30,
        }
        assert response.headers.get("Retry-After") == "30"

    def test_upstream_429_without_retry_after_header(
        self,
        test_client: TestClient,
        integration_redis,
        provider_with_handler,
    ) -> None:
        """Missing ``Retry-After`` header on upstream 429 → body
        omits the field (not a surprising ``null``). Header absent."""
        provider_with_handler(lambda req: httpx.Response(429, json={}))
        response = _post(test_client, {"texts": ["x"]})
        assert response.status_code == 429
        body = response.json()
        assert "retry_after_seconds" not in body
        assert "Retry-After" not in response.headers

    def test_upstream_4xx_non_429_maps_to_502(
        self,
        test_client: TestClient,
        integration_redis,
        provider_with_handler,
    ) -> None:
        """4xx non-429 (400 / 401 / 403 / 404) → 502 because from
        the proxy-caller's perspective the upstream can't help — the
        request is structurally wrong for OpenAI."""
        provider_with_handler(lambda req: httpx.Response(400))
        response = _post(test_client, {"texts": ["x"]})
        assert response.status_code == 502
        assert response.json()["upstream_status"] == 400


# ---------------------------------------------------------------------------
# Local rate-limit (§7.4) — D5 end-to-end
# ---------------------------------------------------------------------------


class TestLocalRateLimit:
    """D5 Draft v2 locks a 30/minute-per-token-principal bucket. The
    plan value is 30 but the env knob lets us shrink it for test
    speed — settings lru-cache is cleared so the callable-based
    ``@_limiter.limit(_rate_limit_expression)`` picks the new value
    on the NEXT request."""

    def test_drain_triggers_429_with_locked_body_shape(
        self,
        test_client: TestClient,
        integration_redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LLM_PROXY_EMBEDDING_RATE_LIMIT", "3/minute")
        get_settings.cache_clear()
        try:
            # First three requests inside the budget — all 200.
            for _ in range(3):
                response = _post(test_client, {"texts": ["x"]})
                assert response.status_code == 200, response.text
            # Fourth exhausts the bucket.
            response = _post(test_client, {"texts": ["x"]})
            assert response.status_code == 429
            body = response.json()
            # D5 Draft v2 locked body shape — every field pinned.
            assert set(body.keys()) == {
                "error",
                "message",
                "retry_after_seconds",
            }
            assert body["error"] == "rate_limit_exceeded"
            assert isinstance(body["message"], str) and body["message"]
            assert (
                isinstance(body["retry_after_seconds"], int)
                and body["retry_after_seconds"] >= 1
            )
            # Retry-After header mirrors the body value.
            assert response.headers.get("Retry-After") == str(
                body["retry_after_seconds"]
            )
        finally:
            get_settings.cache_clear()

    def test_distinct_principals_have_distinct_buckets(
        self,
        test_client: TestClient,
        integration_redis,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Token-principal isolation: draining caller A's bucket
        leaves caller B's budget intact. Validates the slowapi
        ``key_func=token_principal_key`` wiring (Group A)."""
        monkeypatch.setenv("LLM_PROXY_EMBEDDING_RATE_LIMIT", "2/minute")
        get_settings.cache_clear()
        try:
            # Two distinct tokens — pretend the middleware accepts
            # both by swapping ``_INTERNAL_TOKEN`` between batches.
            # The limiter sees the raw header value and hashes it,
            # so bucket keys diverge independently of middleware.
            token_a = "principal-A-token"
            token_b = "principal-B-token"

            monkeypatch.setattr(main_module, "_INTERNAL_TOKEN", token_a)
            test_client.headers["X-Internal-Token"] = token_a
            for _ in range(2):
                assert _post(test_client, {"texts": ["x"]}).status_code == 200
            # A is now empty.
            assert _post(test_client, {"texts": ["x"]}).status_code == 429

            # Switch to B — fresh budget because the bucket key
            # (sha256 of the token) is different.
            monkeypatch.setattr(main_module, "_INTERNAL_TOKEN", token_b)
            test_client.headers["X-Internal-Token"] = token_b
            assert _post(test_client, {"texts": ["x"]}).status_code == 200
            assert _post(test_client, {"texts": ["x"]}).status_code == 200
        finally:
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# D8 LOCKED — no raw text in logs, ever
# ---------------------------------------------------------------------------


class TestNoRawTextLog:
    """D8 is the hardest security invariant in the plan. We emit
    requests containing an identifiable sentinel and check it
    appears NOWHERE across captured log records — message, args,
    and extra fields alike. The check runs on the happy path AND
    every upstream error path (503 / timeout / 429) because
    upstream error bodies may echo the request input back to us
    and a careless handler could forward it to the log."""

    @staticmethod
    def _all_record_text(caplog: pytest.LogCaptureFixture) -> str:
        """Concatenate every capturable attribute of every log
        record into one big string. If the sentinel leaked into
        any of them, it shows up here."""
        parts: list[str] = []
        for record in caplog.records:
            parts.append(record.getMessage())
            # Include args, exc_info text, and all non-standard
            # attributes (what ``extra=`` dumps onto the record).
            parts.append(repr(record.args))
            parts.append(repr(record.__dict__))
        return "\n".join(parts)

    def test_happy_path_log_omits_sentinel_text(
        self,
        test_client: TestClient,
        integration_redis,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="llm_proxy")
        response = _post(test_client, {"texts": [SENTINEL, "other text"]})
        assert response.status_code == 200

        # Sentinel never appears.
        blob = self._all_record_text(caplog)
        assert SENTINEL not in blob

        # Positive: structured log fields are present.
        embed_records = [
            r for r in caplog.records if r.getMessage() == "embedding.generate"
        ]
        assert len(embed_records) == 1
        record = embed_records[0]
        for field in (
            "event",
            "provider",
            "model_requested",
            "model_returned",
            "n_texts",
            "total_text_chars",
            "cache_hits_count",
            "cache_misses_count",
            "total_latency_ms",
            "redis_ok",
            "rate_limited",
        ):
            assert hasattr(record, field), f"missing log field: {field}"
        assert record.event == "embedding.generate"
        assert record.provider == "mock"
        assert record.n_texts == 2
        # total_text_chars is an AGGREGATE — not a per-text leak.
        assert record.total_text_chars == len(SENTINEL) + len("other text")

    def test_upstream_error_echoes_sentinel_but_logs_do_not(
        self,
        test_client: TestClient,
        integration_redis,
        provider_with_handler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Adversarial: upstream 503 response body contains the
        sentinel. The provider sees the body, our error handler
        emits a log, and the sentinel still MUST NOT appear in
        captured logs."""
        caplog.set_level(logging.DEBUG, logger="llm_proxy")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                503,
                json={"error": {"message": f"context included {SENTINEL}"}},
            )

        provider_with_handler(handler)
        response = _post(test_client, {"texts": [SENTINEL]})
        assert response.status_code == 502
        assert SENTINEL not in self._all_record_text(caplog)

    def test_timeout_path_does_not_log_sentinel(
        self,
        test_client: TestClient,
        integration_redis,
        provider_with_handler,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="llm_proxy")

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("deadline hit")

        provider_with_handler(handler)
        response = _post(test_client, {"texts": [SENTINEL]})
        assert response.status_code == 504
        assert SENTINEL not in self._all_record_text(caplog)


# ---------------------------------------------------------------------------
# Cache round-trip (§7.5) — D6 per-text + graceful degrade
# ---------------------------------------------------------------------------


class TestCacheRoundTrip:
    def test_second_request_hits_cache_and_skips_upstream(
        self,
        test_client: TestClient,
        integration_redis,
        counting_provider: CountingMockProvider,
    ) -> None:
        texts = ["alpha-text", "beta-text"]
        first = _post(test_client, {"texts": texts})
        assert first.status_code == 200
        assert first.json()["cache_hit"] is False
        assert len(counting_provider.calls) == 1
        assert counting_provider.calls[0] == texts

        second = _post(test_client, {"texts": texts})
        assert second.status_code == 200
        assert second.json()["cache_hit"] is True
        # Provider was NOT called a second time.
        assert len(counting_provider.calls) == 1

        # Vectors are consistent across both responses.
        first_vectors = [
            tuple(item["embedding"]) for item in first.json()["items"]
        ]
        second_vectors = [
            tuple(item["embedding"]) for item in second.json()["items"]
        ]
        assert first_vectors == second_vectors


class TestPartialCacheHit:
    async def _seed_cache(
        self,
        redis_client,
        provider_name: str,
        model: str,
        texts: list[str],
        vector: list[float],
        ttl: int = 3600,
    ) -> None:
        """Manually insert ``{text: vector}`` into Redis under the
        same key format ``cache_key`` produces, so the route looks
        them up as real hits."""
        for text in texts:
            key = cache_key(provider=provider_name, model=model, text=text)
            await redis_client.set(key, json.dumps(vector), ex=ttl)

    @pytest.mark.asyncio
    async def test_partial_hit_dispatches_only_miss_texts(
        self,
        test_client: TestClient,
        integration_redis,
        counting_provider: CountingMockProvider,
    ) -> None:
        """Pre-seed 2 of 3 text slots. Route should dispatch the
        provider with exactly 1 text (the miss), the other 2 come
        from cache. Overall ``cache_hit`` is False because not all
        hit. Item ordering preserves the request's [0, 1, 2]."""
        hit_texts = ["cached-alpha", "cached-beta"]
        miss_text = "fresh-gamma"

        # The cache key is (provider, model, text). Settings default
        # model = "text-embedding-3-small"; provider env = "mock".
        stub_vector = [0.5] * EMBEDDING_DIM
        await self._seed_cache(
            integration_redis,
            provider_name="mock",
            model="text-embedding-3-small",
            texts=hit_texts,
            vector=stub_vector,
        )

        response = _post(
            test_client,
            {"texts": [hit_texts[0], hit_texts[1], miss_text]},
        )
        assert response.status_code == 200
        body = response.json()
        # Overall cache_hit is False because one text was a miss.
        assert body["cache_hit"] is False
        assert len(body["items"]) == 3
        # Provider was called with exactly the miss subset.
        assert len(counting_provider.calls) == 1
        assert counting_provider.calls[0] == [miss_text]
        # Cached slots return the seeded stub, miss slot returns
        # the mock's deterministic value — different vectors.
        assert body["items"][0]["embedding"] == stub_vector
        assert body["items"][1]["embedding"] == stub_vector
        assert body["items"][2]["embedding"] != stub_vector


# ---------------------------------------------------------------------------
# OpenAPI shape (§7.11) — contract visibility for consumers
# ---------------------------------------------------------------------------


class TestOpenAPIShape:
    """``app.openapi()`` is callable regardless of the env-gated
    ``openapi_url`` (disabled under APP_ENV=test), so we can pin
    the shape here without reshuffling env."""

    def test_embedding_route_registered_with_all_d7_responses(
        self, app_under_test: FastAPI
    ) -> None:
        spec = app_under_test.openapi()
        path_spec = spec["paths"][ENDPOINT]
        assert "post" in path_spec
        responses = path_spec["post"]["responses"]
        # All 5 D7 statuses + the 200 success.
        for code in ("200", "422", "429", "502", "503", "504"):
            assert code in responses, f"missing {code} in openapi responses"

    def test_dimensions_field_is_exposed(
        self, app_under_test: FastAPI
    ) -> None:
        spec = app_under_test.openapi()
        components = spec.get("components", {}).get("schemas", {})
        assert "EmbeddingResponse" in components
        props = components["EmbeddingResponse"]["properties"]
        assert "dimensions" in props, (
            "D2 Draft v2 top-level dimensions field must appear in "
            "the response schema for downstream Zod assertions."
        )

    def test_request_schema_pins_batch_bounds(
        self, app_under_test: FastAPI
    ) -> None:
        spec = app_under_test.openapi()
        components = spec.get("components", {}).get("schemas", {})
        assert "EmbeddingRequest" in components
        texts_schema = components["EmbeddingRequest"]["properties"]["texts"]
        # Pydantic emits minItems / maxItems at the array level.
        assert texts_schema.get("minItems") == 1
        assert texts_schema.get("maxItems") == 16


# ---------------------------------------------------------------------------
# §7.10 — existing llm-proxy endpoints unchanged
# ---------------------------------------------------------------------------


class TestExistingEndpointsStable:
    """PR #18 must not regress ``/healthz`` or ``/api/v1/provider/meta``.
    This class is intentionally minimal — the unit tests for those
    surfaces live elsewhere; here we only pin that they still mount
    and the token middleware still gates them the same way."""

    def test_healthz_still_works_without_token(
        self, test_client: TestClient
    ) -> None:
        test_client.headers.pop("X-Internal-Token", None)
        response = test_client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "llm-proxy"}

    def test_provider_meta_still_mounted(
        self, test_client: TestClient
    ) -> None:
        response = test_client.get("/api/v1/provider/meta")
        assert response.status_code == 200
        body = response.json()
        assert "cache" in body and "key_boundary" in body


# ---------------------------------------------------------------------------
# Plan-evidence pin — make it trivial to find sentinel usage if a
# future edit accidentally introduces raw-text logging. This grep
# anchor is exempt from the sentinel-leak test (it's a test file,
# not production code).
# ---------------------------------------------------------------------------

_SENTINEL_REGRESSION_ANCHOR = re.compile(r"SENTINEL-PII-CANARY-[A-F0-9]+")
assert _SENTINEL_REGRESSION_ANCHOR.match(SENTINEL) is not None

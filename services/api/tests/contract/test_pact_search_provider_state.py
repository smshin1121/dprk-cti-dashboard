"""Regression guard for Pact's populated /search provider-state override.

The contract-verify CI job boots a long-lived uvicorn process without a
real llm-proxy sidecar. The populated search state therefore has to
install a deterministic ``get_embedding_client`` dependency override so
the hybrid path can populate ``vector_rank`` during Pact verification.
That override must also be cleared on the next state-change request so it
does not leak into unrelated interactions.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Response

from api.deps import get_embedding_client
from api.main import app
from api.routers import pact_states


@pytest.mark.asyncio
async def test_search_populated_state_toggles_embedding_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Populated search state installs the stub; next state clears it."""

    request = SimpleNamespace(app=app)
    app.dependency_overrides.pop(get_embedding_client, None)

    monkeypatch.setattr(
        pact_states,
        "_ensure_search_populated_fixture",
        AsyncMock(),
    )
    monkeypatch.setattr(
        pact_states,
        "_seed_analyst_session",
        AsyncMock(),
    )

    try:
        await pact_states.provider_states(
            request=request,
            payload=pact_states._ProviderStatePayload(
                state=(
                    "seeded search populated fixture "
                    "and an authenticated analyst session"
                )
            ),
            response=Response(),
            session_store=AsyncMock(),
            session=AsyncMock(),
        )

        override = app.dependency_overrides.get(get_embedding_client)
        assert override is not None, (
            "search populated provider state did not install the "
            "embedding override; contract-verify would stay FTS-only"
        )

        stub = override()
        result = await stub.embed(["lazarus"])
        assert len(result.vectors) == 1
        assert result.vectors[0][0] > result.vectors[0][1] > result.vectors[0][2]

        await pact_states.provider_states(
            request=request,
            payload=pact_states._ProviderStatePayload(
                state="no valid session cookie"
            ),
            response=Response(),
            session_store=AsyncMock(),
            session=AsyncMock(),
        )
        assert get_embedding_client not in app.dependency_overrides, (
            "embedding override leaked into the next interaction"
        )
    finally:
        app.dependency_overrides.pop(get_embedding_client, None)

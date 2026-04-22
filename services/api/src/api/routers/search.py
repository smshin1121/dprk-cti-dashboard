"""Search router - PR #17 Group B.

Exposes ``GET /api/v1/search`` as the FTS-only MVP over reports.

Locked scope for this slice:
- Reports only (D1). No codenames / incidents / alerts yet.
- PostgreSQL FTS only (D2/D3) via ``search_service``. Hybrid/vector
  search is a follow-up PR once llm-proxy gains an embedding endpoint.
- Filters are date-only (D8): ``date_from`` / ``date_to`` plus
  ``limit``. No tag/source/group/tlp/q-subfilters.
- Rate limit is the same 60/min/user read policy as the rest of the
  read surface, but a per-decorated-route bucket (slowapi semantics).
- RBAC matches the five read roles.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.schemas import CurrentUser
from ..db import get_db
from ..deps import get_embedding_client, require_role
from ..embedding_client import LlmProxyEmbeddingClient
from ..rate_limit import get_limiter
from ..read import search_cache, search_service
from ..schemas.read import (
    SEARCH_LIMIT_DEFAULT,
    SEARCH_LIMIT_MAX,
    SEARCH_LIMIT_MIN,
    SearchResponse,
)

router = APIRouter()

_limiter = get_limiter()
_READ_ROLES = ("analyst", "researcher", "policy", "soc", "admin")


@router.get(
    "",
    response_model=SearchResponse,
    summary="Full-text search reports",
    description=(
        "Hybrid report search — PostgreSQL FTS fused with pgvector cosine "
        "kNN via RRF (PR #19b). Query text is required, whitespace-only "
        "queries are rejected with 422, and the filter surface is "
        "intentionally narrow: `date_from`, `date_to`, and `limit` only. "
        "Response envelope is `{items, total_hits, latency_ms}` with "
        "per-hit `fts_rank` (`ts_rank_cd` float; 0.0 for a vector-only "
        "hit) and `vector_rank` (1-indexed rank inside the vector-kNN "
        "top-N, or `null` for an FTS-only hit). Degrades to FTS-only "
        "(every hit carries `vector_rank: null`) when the llm-proxy "
        "embedding path is transient-unavailable or when the corpus "
        "embedding-coverage ratio is below the configured threshold; "
        "the degraded signal lives in structured logs only (no body "
        "field). llm-proxy permanent errors surface as HTTP 500."
    ),
    responses={
        200: {
            "description": (
                "Search hits ordered by RRF fused score (`rrf_score DESC, "
                "report.id DESC`) on the hybrid path, or by `fts_rank DESC, "
                "report.id DESC` on the degraded FTS-only path. Envelope "
                "shape is identical across both paths. D10 empty envelope "
                "fires when there are no matches."
            ),
            "content": {
                "application/json": {
                    "examples": {
                        "happy": {
                            "summary": "One hybrid hit with vector_rank populated",
                            "value": {
                                "items": [
                                    {
                                        "report": {
                                            "id": 999060,
                                            "title": "Lazarus targets SK crypto exchanges",
                                            "url": "https://pact.test/search/lazarus-1",
                                            "url_canonical": "https://pact.test/search/lazarus-1",
                                            "published": "2026-03-15",
                                            "source_id": 1,
                                            "source_name": "Vendor",
                                            "lang": "en",
                                            "tlp": "WHITE",
                                        },
                                        "fts_rank": 0.0759,
                                        # PR #19b — populated 1-indexed
                                        # rank from the vector-kNN leg
                                        # filling PR #17 D9's forward-
                                        # compat slot.
                                        "vector_rank": 1,
                                    }
                                ],
                                "total_hits": 1,
                                "latency_ms": 42,
                            },
                        },
                        "empty": {
                            "summary": "No matches",
                            "value": {
                                "items": [],
                                "total_hits": 0,
                                "latency_ms": 12,
                            },
                        },
                    }
                }
            },
        },
        401: {"description": "Missing or invalid session cookie"},
        403: {
            "description": (
                "Authenticated role is not analyst / researcher / policy "
                "/ soc / admin"
            )
        },
        422: {
            "description": (
                "Invalid query parameter: missing `q`, blank/whitespace-only `q`, "
                "invalid ISO date, or `limit` outside 1..50. Plan D12 uniform 422."
            ),
            "content": {
                "application/json": {
                    "examples": {
                        "blank_q": {
                            "summary": "Whitespace-only query rejected",
                            "value": {
                                "detail": [
                                    {
                                        "loc": ["query", "q"],
                                        "msg": "q must not be blank",
                                        "type": "value_error.blank_query",
                                    }
                                ]
                            },
                        },
                        "limit": {
                            "summary": "Limit out of range",
                            "value": {
                                "detail": [
                                    {
                                        "loc": ["query", "limit"],
                                        "msg": "Input should be less than or equal to 50",
                                        "type": "less_than_equal",
                                    }
                                ]
                            },
                        },
                    }
                }
            },
        },
        429: {
            "description": (
                "Rate limit exceeded - same 60/min/user read policy as the "
                "other read endpoints, but a per-decorated-route bucket. "
                "Exhausting `/search` does NOT consume `/actors` or `/reports` budget."
            ),
            "content": {
                "application/json": {
                    "example": {
                        "error": "rate_limit_exceeded",
                        "message": "60 per 1 minute",
                    }
                }
            },
        },
    },
)
@_limiter.limit("60/minute")
async def search_endpoint(
    request: Request,
    q: Annotated[str, Query(min_length=1)],
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    limit: Annotated[
        int,
        Query(ge=SEARCH_LIMIT_MIN, le=SEARCH_LIMIT_MAX),
    ] = SEARCH_LIMIT_DEFAULT,
    session: AsyncSession = Depends(get_db),
    redis=Depends(search_cache.get_redis_for_search_cache),
    embedding_client: LlmProxyEmbeddingClient | None = Depends(
        get_embedding_client
    ),
    _current_user: CurrentUser = Depends(require_role(*_READ_ROLES)),
) -> Response:
    """Report search endpoint (PR #17 Group B + PR #19b hybrid upgrade).

    ``embedding_client`` is injected via ``Depends(get_embedding_client)``
    — ``None`` when ``LLM_PROXY_URL`` / ``LLM_PROXY_INTERNAL_TOKEN`` are
    empty (feature disabled — FTS-only behavior). Non-None activates
    the hybrid dispatch in ``search_service.get_search_results``.
    """
    q_stripped = q.strip()
    if not q_stripped:
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {
                        "loc": ["query", "q"],
                        "msg": "q must not be blank",
                        "type": "value_error.blank_query",
                    }
                ]
            },
        )

    result = await search_service.get_search_results(
        session,
        redis,
        q=q_stripped,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        embedding_client=embedding_client,
    )
    return SearchResponse.model_validate(result.payload)

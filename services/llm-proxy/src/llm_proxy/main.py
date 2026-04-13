import os

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .routers import provider

# ---------------------------------------------------------------------------
# Internal shared-secret guard.
# LLM_PROXY_INTERNAL_TOKEN must be set in the environment; the proxy is
# internal-network-only but we still enforce a shared secret so that a
# misconfigured network rule cannot expose the OpenAI key publicly.
# ---------------------------------------------------------------------------
_INTERNAL_TOKEN = os.environ.get("LLM_PROXY_INTERNAL_TOKEN", "")
_APP_ENV = os.environ.get("APP_ENV", "dev")

# Expose docs only in dev.
_docs_url = "/docs" if _APP_ENV == "dev" else None
_redoc_url = "/redoc" if _APP_ENV == "dev" else None
_openapi_url = "/openapi.json" if _APP_ENV == "dev" else None

app = FastAPI(
    title="DPRK CTI LLM Proxy",
    version="0.1.0",
    openapi_version="3.1.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)


@app.middleware("http")
async def require_internal_token(request: Request, call_next) -> Response:
    """Fail-closed shared-secret check for all non-health routes.

    Requests must carry the header:  X-Internal-Token: <LLM_PROXY_INTERNAL_TOKEN>

    If LLM_PROXY_INTERNAL_TOKEN is empty the service refuses ALL requests so
    that a missing env var is caught immediately at runtime rather than silently
    allowing unauthenticated access.
    """
    # Allow health probe without a token.
    if request.url.path == "/healthz":
        return await call_next(request)

    if not _INTERNAL_TOKEN:
        return JSONResponse(
            status_code=503,
            content={"detail": "LLM_PROXY_INTERNAL_TOKEN not configured — service unavailable."},
        )

    provided = request.headers.get("X-Internal-Token", "")
    if provided != _INTERNAL_TOKEN:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid X-Internal-Token header."},
        )

    return await call_next(request)


app.include_router(provider.router, prefix="/api/v1/provider", tags=["provider"])


@app.get("/healthz", tags=["ops"])
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "service": "llm-proxy"}

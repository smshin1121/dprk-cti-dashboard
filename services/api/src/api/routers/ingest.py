from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..deps import require_role

router = APIRouter()


@router.post("/rss/run", dependencies=[Depends(require_role("admin"))])
async def run_rss_ingest() -> JSONResponse:
    """§5.1 / §9.3 Trigger a manual RSS ingest run. Admin role required."""
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented", "endpoint": "ingest.rss.run"},
    )


@router.get("/status")
async def ingest_status() -> JSONResponse:
    """§5.1 Return the current ingest pipeline status and recent run metadata."""
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented", "endpoint": "ingest.status"},
    )

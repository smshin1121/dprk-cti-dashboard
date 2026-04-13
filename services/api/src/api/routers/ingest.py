from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/rss/run")
def run_rss_ingest() -> JSONResponse:
    """§5.1 Trigger a manual RSS ingest run (normally scheduled via worker)."""
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented", "endpoint": "ingest.rss.run"},
    )


@router.get("/status")
def ingest_status() -> JSONResponse:
    """§5.1 Return the current ingest pipeline status and recent run metadata."""
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented", "endpoint": "ingest.status"},
    )

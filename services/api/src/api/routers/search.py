from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("")
def search(q: str = "", limit: int = 20) -> JSONResponse:
    """§5.2 Global full-text + semantic search across reports/alerts/actors."""
    return JSONResponse(
        status_code=501,
        content={
            "status": "not_implemented",
            "endpoint": "search",
            "q": q,
            "limit": limit,
        },
    )

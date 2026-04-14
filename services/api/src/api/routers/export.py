from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/stix")
async def export_stix() -> JSONResponse:
    """§5.6 Export indicators and reports as STIX 2.1 bundle."""
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented", "endpoint": "export.stix"},
    )


@router.get("/pdf")
async def export_pdf() -> JSONResponse:
    """§5.6 Export a rendered PDF briefing for the selected report(s)."""
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented", "endpoint": "export.pdf"},
    )


@router.get("/csv")
async def export_csv() -> JSONResponse:
    """§5.6 Export tabular data (IoCs, alerts, reports) as CSV."""
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented", "endpoint": "export.csv"},
    )

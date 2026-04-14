from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/{report_id}/similar")
def similar_reports(report_id: int, k: int = 10) -> JSONResponse:
    """§5.2 pgvector similarity search for related reports.

    Stub: returns 501 for consistency with all other protected endpoints.
    The verify_token dependency would raise 501 before this handler runs
    anyway, so returning a fake 200 body here was misleading.

    Intended shape (for future implementation):
        {
            "report_id": int,
            "k": int,
            "items": list[SimilarReportDTO],  # ranked by cosine distance
        }
    """
    return JSONResponse(
        status_code=501,
        content={
            "status": "not_implemented",
            "endpoint": "reports.similar",
            "report_id": report_id,
            "k": k,
        },
    )


@router.post("/review/{report_id}")
def review_report(report_id: int) -> JSONResponse:
    """§5.3 Human-in-the-loop approve/reject workflow for AI-generated reports."""
    return JSONResponse(
        status_code=501,
        content={
            "status": "not_implemented",
            "endpoint": "reports.review",
            "report_id": report_id,
        },
    )

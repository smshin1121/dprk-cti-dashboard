from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("")
def list_alerts() -> JSONResponse:
    """§5.5 Alerts feed (paginated).

    Stub: returns 501 for consistency with all other protected endpoints.
    The verify_token dependency would raise 501 before this handler runs
    anyway, so returning a fake 200 body here was misleading.

    Intended shape (for future implementation):
        {"items": list[AlertDTO], "total": int, "page": int, "limit": int}
    """
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented", "endpoint": "alerts.list"},
    )


@router.post("/{alert_id}/ack")
def ack_alert(alert_id: int) -> JSONResponse:
    """§5.5 Acknowledge an alert and mark it handled."""
    return JSONResponse(
        status_code=501,
        content={
            "status": "not_implemented",
            "endpoint": "alerts.ack",
            "alert_id": alert_id,
        },
    )


@router.post("/rules")
def create_alert_rule() -> JSONResponse:
    """§5.5 Create a new alert rule (CRUD — create stub only)."""
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented", "endpoint": "alerts.rules.create"},
    )

from fastapi import APIRouter

router = APIRouter()


@router.get("")
def meta() -> dict[str, object]:
    """Public service metadata endpoint (§7.6)."""
    return {
        "phase": "implementation-prep",
        "services": ["frontend", "api", "worker", "llm-proxy", "db", "cache"],
        "planned_endpoints": [
            "/api/v1/auth/login",
            "/api/v1/auth/me",
            "/api/v1/ingest/rss/run",
            "/api/v1/ingest/status",
            "/api/v1/reports/{id}/similar",
            "/api/v1/reports/review/{id}",
            "/api/v1/analytics/attack-heatmap",
            "/api/v1/analytics/attribution-graph",
            "/api/v1/analytics/geopolitical",
            "/api/v1/analytics/forecast",
            "/api/v1/search",
            "/api/v1/alerts",
            "/api/v1/alerts/{id}/ack",
            "/api/v1/alerts/rules",
            "/api/v1/export/stix",
            "/api/v1/export/pdf",
            "/api/v1/export/csv",
        ],
    }

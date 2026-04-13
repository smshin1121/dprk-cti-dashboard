from fastapi import APIRouter

router = APIRouter()


@router.get("/meta")
def provider_meta() -> dict[str, object]:
    return {
        "cache": "planned",
        "key_boundary": "llm-proxy only",
        "usage_metrics": "planned",
    }

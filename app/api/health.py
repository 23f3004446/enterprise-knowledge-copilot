from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "service": settings.api_title,
        "environment": settings.app_env,
    }


@router.get("/")
def root() -> dict:
    return {"message": f"{settings.api_title} API is running."}

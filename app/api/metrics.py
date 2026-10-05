from __future__ import annotations

from fastapi import APIRouter

from app.core.telemetry import metrics_response

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics() -> object:
    return metrics_response()

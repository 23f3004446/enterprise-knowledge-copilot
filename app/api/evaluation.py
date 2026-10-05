from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user_from_credentials
from scripts.evaluate import run_evaluation

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


def _require_admin(user: dict) -> None:
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins may run evaluations.")


@router.post("/run")
def run(current_user: dict = Depends(get_current_user_from_credentials)) -> dict:
    _require_admin(current_user)
    try:
        return run_evaluation()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Evaluation could not complete: {type(exc).__name__}.",
        ) from exc


@router.get("/results")
def results(current_user: dict = Depends(get_current_user_from_credentials)) -> dict:
    _require_admin(current_user)
    from pathlib import Path
    import json

    result_path = Path("data/evaluation/results.json")
    if not result_path.exists():
        return {"status": "not_run", "message": "Run POST /evaluation/run to create actual evaluation results."}
    with result_path.open(encoding="utf-8") as file:
        return json.load(file)

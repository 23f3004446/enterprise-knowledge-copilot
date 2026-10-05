from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user_from_credentials
from app.core.telemetry import CACHE_HITS, CACHE_MISSES, CHAT_QUERY_COUNT
from app.db.database import get_db
from app.db.models import DocumentChunk, DocumentRecord

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
def overview(
    current_user: dict = Depends(get_current_user_from_credentials),
    db: Session = Depends(get_db),
) -> dict:
    if current_user.get("role") != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    results_file = Path("data/evaluation/results.json")
    return {
        "documents": db.query(DocumentRecord).count(),
        "chunks": db.query(DocumentChunk).count(),
        "queries": int(CHAT_QUERY_COUNT._value.get()),
        "cache_hits": int(CACHE_HITS._value.get()),
        "cache_misses": int(CACHE_MISSES._value.get()),
        "cache_hit_rate": (
            CACHE_HITS._value.get() / (CACHE_HITS._value.get() + CACHE_MISSES._value.get())
            if CACHE_HITS._value.get() + CACHE_MISSES._value.get()
            else 0.0
        ),
        "evaluation": json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else None,
    }

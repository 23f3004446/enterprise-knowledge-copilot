from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import allowed_access_levels
from app.core.security import get_current_user_from_credentials
from app.db.database import get_db
from app.db.models import DocumentChunk, DocumentRecord
from app.schemas.schemas import DocumentIngestRequest
from app.services.document_ingestion import ingest_path, save_upload

router = APIRouter(prefix="/documents", tags=["documents"])


def _require_admin(user: dict) -> None:
    if user.get("role") != "ADMIN":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins may manage documents.")


@router.get("")
def list_documents(
    current_user: dict = Depends(get_current_user_from_credentials),
    db: Session = Depends(get_db),
) -> dict:
    access = allowed_access_levels(current_user.get("role", ""))
    documents = db.query(DocumentRecord).filter(DocumentRecord.access_role.in_(access)).order_by(DocumentRecord.filename).all()
    return {
        "documents": [
            {
                "document_id": doc.document_id,
                "filename": doc.filename,
                "source_type": doc.source_type,
                "access_level": doc.access_role,
                "chunk_count": db.query(DocumentChunk).filter_by(document_id=doc.document_id).count(),
            }
            for doc in documents
        ]
    }


@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload_document(
    file: UploadFile = File(...),
    access_level: str = Form("EMPLOYEE"),
    department: str = Form("General"),
    current_user: dict = Depends(get_current_user_from_credentials),
    db: Session = Depends(get_db),
) -> dict:
    _require_admin(current_user)
    access_level = access_level.upper()
    if access_level not in {"PUBLIC", "EMPLOYEE", "MANAGER", "ADMIN"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid access level.")
    try:
        data = file.file.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Maximum upload size is 20 MiB.")
        path = save_upload(file.filename or "document", data, access_level=access_level)
        document_id, chunk_count = ingest_path(db, path, access_level=access_level, department=department)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"document_id": document_id, "filename": path.name, "access_level": access_level, "chunks": chunk_count}


@router.post("/ingest", status_code=status.HTTP_200_OK)
def ingest_existing_document(
    payload: DocumentIngestRequest,
    current_user: dict = Depends(get_current_user_from_credentials),
    db: Session = Depends(get_db),
) -> dict:
    _require_admin(current_user)
    access_level = payload.access_level.upper()
    if access_level not in {"PUBLIC", "EMPLOYEE", "MANAGER", "ADMIN"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid access level.")
    root = Path(settings.raw_documents_dir).resolve()
    path = (root / payload.relative_path).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path must stay inside the raw document directory.")
    try:
        document_id, chunks = ingest_path(db, path, access_level, payload.department)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"document_id": document_id, "chunks": chunks}

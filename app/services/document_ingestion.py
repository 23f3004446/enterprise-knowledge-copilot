from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DocumentChunk, DocumentRecord

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".markdown"}


@dataclass(frozen=True)
class ParsedPage:
    number: int | None
    text: str


def parse_document(path: Path) -> list[ParsedPage]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        return [ParsedPage(i, page.extract_text() or "") for i, page in enumerate(reader.pages, start=1)]
    if suffix in {".txt", ".md", ".markdown"}:
        return [ParsedPage(None, path.read_text(encoding="utf-8", errors="replace"))]
    raise ValueError(f"Unsupported document type: {suffix or '(no extension)'}")


def chunk_text(text: str, size: int | None = None, overlap: int | None = None) -> list[str]:
    size = settings.chunk_size if size is None else size
    overlap = settings.chunk_overlap if overlap is None else overlap
    if size < 1 or overlap < 0 or overlap >= size:
        raise ValueError("CHUNK_SIZE must be positive and CHUNK_OVERLAP must be in [0, CHUNK_SIZE).")

    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    step = size - overlap
    while start < len(words):
        end = min(start + size, len(words))
        part = " ".join(words[start:end]).strip()
        if part:
            chunks.append(part)
        if end == len(words):
            break
        start += step
    return chunks


def _stable_document_id(name: str, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()[:16]
    safe_stem = "".join(char.lower() if char.isalnum() else "-" for char in Path(name).stem).strip("-")
    return f"{safe_stem[:80] or 'document'}-{digest}"


def ingest_path(
    db: Session,
    path: Path,
    access_level: str = "EMPLOYEE",
    department: str = "General",
) -> tuple[str, int]:
    if not path.is_file():
        raise FileNotFoundError(f"Document does not exist: {path}")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported document type: {path.suffix}")

    raw = path.read_bytes()
    pages = parse_document(path)
    document_id = _stable_document_id(path.name, raw)
    content = "\n".join(page.text for page in pages)

    record = db.query(DocumentRecord).filter_by(document_id=document_id).one_or_none()
    if record is not None and record.content == content and record.access_role == access_level:
        existing_chunks = db.query(DocumentChunk).filter_by(document_id=document_id).all()
        if department == "General" or all(chunk.department == department for chunk in existing_chunks):
            return document_id, len(existing_chunks)

    if record is None:
        record = DocumentRecord(
            document_id=document_id,
            filename=path.name,
            source_type=path.suffix.lower().lstrip("."),
            access_role=access_level,
            content=content,
        )
        db.add(record)
        db.flush()
    else:
        record.content = content
        record.access_role = access_level
        db.query(DocumentChunk).filter_by(document_id=document_id).delete()

    chunk_count = 0
    for page in pages:
        for ordinal, text in enumerate(chunk_text(page.text), start=1):
            chunk_id = hashlib.sha256(
                f"{document_id}:{page.number}:{ordinal}:{text}".encode("utf-8")
            ).hexdigest()
            db.add(
                DocumentChunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    document_name=path.name,
                    content=text,
                    page=page.number,
                    access_level=access_level,
                    department=department,
                    source_type=path.suffix.lower().lstrip("."),
                )
            )
            chunk_count += 1
    db.commit()
    return document_id, chunk_count


def save_upload(filename: str, content: bytes, access_level: str = "EMPLOYEE") -> Path:
    safe_name = os.path.basename(filename)
    if not safe_name or Path(safe_name).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError("Only PDF, TXT, and Markdown documents are supported.")
    access_level = access_level.upper()
    if access_level not in {"PUBLIC", "EMPLOYEE", "MANAGER", "ADMIN"}:
        raise ValueError("Invalid document access level.")
    upload_dir = (Path(settings.uploaded_documents_dir) / access_level).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / safe_name
    destination.write_bytes(content)
    return destination

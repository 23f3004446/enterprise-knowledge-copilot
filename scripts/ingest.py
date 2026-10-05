from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.database import SessionLocal, init_db
from app.services.document_ingestion import SUPPORTED_SUFFIXES, ingest_path


def main() -> None:
    raw_dir = Path(settings.raw_documents_dir)
    if not raw_dir.exists():
        raise SystemExit(f"Raw document directory does not exist: {raw_dir.resolve()}")
    init_db()
    upload_dir = Path(settings.uploaded_documents_dir)
    documents = sorted(
        path
        for root in (raw_dir, upload_dir)
        if root.exists()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not documents:
        raise SystemExit(f"No PDF, TXT, or Markdown documents found in {raw_dir.resolve()}")

    with SessionLocal() as db:
        for path in documents:
            level = path.parent.name.upper()
            if level not in {"PUBLIC", "EMPLOYEE", "MANAGER", "ADMIN"}:
                level = "EMPLOYEE"
            document_id, chunks = ingest_path(db, path, access_level=level, department="General")
            print(f"{path.name}: {chunks} chunks ({level}, id={document_id})")


if __name__ == "__main__":
    main()

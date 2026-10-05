from pathlib import Path

from app.db.database import Base
from app.db.models import DocumentChunk, DocumentRecord
from app.services.document_ingestion import chunk_text, ingest_path, parse_document
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_chunking_respects_overlap_and_empty_input() -> None:
    chunks = chunk_text("one two three four five six seven", size=4, overlap=1)
    assert chunks == ["one two three four", "four five six seven"]
    assert chunk_text("   ") == []
    import pytest

    with pytest.raises(ValueError):
        chunk_text("words", size=0, overlap=0)


def test_markdown_ingestion_persists_chunks_and_access_metadata(tmp_path: Path) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    document = tmp_path / "policy.md"
    document.write_text("# Leave\nEmployees receive twenty days of annual leave.", encoding="utf-8")
    with Session(engine) as db:
        document_id, count = ingest_path(db, document, access_level="EMPLOYEE", department="HR")
        assert count == 1
        record = db.query(DocumentRecord).filter_by(document_id=document_id).one()
        chunk = db.query(DocumentChunk).filter_by(document_id=document_id).one()
        assert record.source_type == "md"
        assert chunk.document_name == "policy.md"
        assert chunk.page is None
        assert chunk.access_level == "EMPLOYEE"
        assert chunk.department == "HR"
        assert "twenty days" in chunk.content


def test_pdf_parser_preserves_page_numbers(tmp_path: Path, monkeypatch) -> None:
    import app.services.document_ingestion as ingestion

    pdf = tmp_path / "one-page.pdf"
    pdf.write_bytes(b"pdf fixture")

    class FakePage:
        def extract_text(self):
            return "A policy sentence on page one."

    class FakePdfReader:
        def __init__(self, _path):
            self.pages = [FakePage(), FakePage()]

    monkeypatch.setattr(ingestion, "PdfReader", FakePdfReader)
    pages = parse_document(pdf)
    assert pages[0].number == 1
    assert pages[1].number == 2
    assert "policy sentence" in pages[0].text

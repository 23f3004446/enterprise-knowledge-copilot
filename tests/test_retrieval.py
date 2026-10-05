from app.db.database import Base
from app.db.models import DocumentChunk, DocumentRecord
from app.services.retrieval import RetrievalService
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import numpy as np


def make_db() -> tuple[object, Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    docs = [
        DocumentRecord(document_id="leave", filename="annual-leave-policy.md", source_type="md", access_role="EMPLOYEE", content=""),
        DocumentRecord(document_id="manager", filename="manager-approval-policy.md", source_type="md", access_role="MANAGER", content=""),
        DocumentRecord(document_id="privileged", filename="privileged-access-policy.md", source_type="md", access_role="ADMIN", content=""),
    ]
    db.add_all(docs)
    db.flush()
    db.add_all(
        [
            DocumentChunk(chunk_id="c-leave", document_id="leave", document_name="annual-leave-policy.md", content="HR-LEAVE-001 annual leave requests have 20 days.", page=None, access_level="EMPLOYEE", department="HR", source_type="md"),
            DocumentChunk(chunk_id="c-manager", document_id="manager", document_name="manager-approval-policy.md", content="MGR-APP-310 managers approve team leave.", page=None, access_level="MANAGER", department="Management", source_type="md"),
            DocumentChunk(chunk_id="c-admin", document_id="privileged", document_name="privileged-access-policy.md", content="IAM-PRIV-520 privileged access requires administrator approval.", page=None, access_level="ADMIN", department="Security", source_type="md"),
        ]
    )
    db.commit()
    return engine, db


def test_permission_filter_is_applied_before_hybrid_retrievers() -> None:
    engine, db = make_db()
    service = RetrievalService()
    observed = []
    service._vector_hits = lambda chunks, *_args, **_kwargs: observed.extend(chunks) or []
    try:
        results = service.search(db, "IAM-PRIV-520 administrator approval", role="EMPLOYEE", rerank=False)
        assert results == []
        assert observed
        assert all(chunk.access_level in {"PUBLIC", "EMPLOYEE"} for chunk in observed)
        assert all(chunk.chunk_id != "c-admin" for chunk in observed)
    finally:
        db.close()
        engine.dispose()


def test_bm25_finds_exact_policy_code_in_authorized_chunk() -> None:
    engine, db = make_db()
    service = RetrievalService()
    service._vector_hits = lambda *_args, **_kwargs: []
    try:
        results = service.search(db, "MGR-APP-310", role="MANAGER", rerank=False)
        assert results
        assert results[0].chunk_id == "c-manager"
        assert results[0].bm25_score > 0
    finally:
        db.close()
        engine.dispose()


def test_faiss_index_persists_role_scoped_mapping(tmp_path, monkeypatch) -> None:
    engine, db = make_db()
    service = RetrievalService()

    class TestEncoder:
        def encode(self, texts, **_kwargs):
            return np.asarray(
                [[1.0, 0.0] if "leave" in text.lower() else [0.0, 1.0] for text in texts],
                dtype="float32",
            )

    monkeypatch.setattr(service, "_get_embedder", lambda: TestEncoder())
    monkeypatch.setattr("app.services.retrieval.settings.index_dir", str(tmp_path))
    try:
        employee_chunks = service._allowed_chunks(db, "EMPLOYEE")
        first = service._vector_hits(employee_chunks, "leave", 5, "EMPLOYEE")
        second = service._vector_hits(employee_chunks, "leave", 5, "EMPLOYEE")
        assert first and second
        assert all(chunk.access_level in {"PUBLIC", "EMPLOYEE"} for chunk, _ in first)
        assert (tmp_path / "employee.faiss").exists()
        assert (tmp_path / "employee.json").exists()
    finally:
        db.close()
        engine.dispose()

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.database import Base, get_db
from app.db.seed import seed_demo_users
from app.main import app
from app.services.document_ingestion import SUPPORTED_SUFFIXES, ingest_path


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with TestSession() as db:
        seed_demo_users(db)
        raw_dir = Path(settings.raw_documents_dir)
        for path in sorted(raw_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                level = path.parent.name.upper()
                if level not in {"PUBLIC", "EMPLOYEE", "MANAGER", "ADMIN"}:
                    level = "EMPLOYEE"
                ingest_path(db, path, access_level=level)

    def override_get_db():
        with TestSession() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()

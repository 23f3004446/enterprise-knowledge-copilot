from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
import uuid

from fastapi import FastAPI, Request
from sqlalchemy.orm import Session

from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.api.evaluation import router as evaluation_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.core.config import settings
from app.core.logging import logger
from app.core.telemetry import ERROR_COUNT, REQUEST_COUNT, REQUEST_LATENCY, instrument_fastapi
from app.db.database import SessionLocal, init_db
from app.db.seed import seed_demo_users
from app.services.document_ingestion import SUPPORTED_SUFFIXES, ingest_path


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing application database tables.")
    init_db()
    db: Session = SessionLocal()
    try:
        seed_demo_users(db)
        document_roots = [Path(settings.raw_documents_dir), Path(settings.uploaded_documents_dir)]
        for raw_dir in document_roots:
            if not raw_dir.exists():
                continue
            for path in sorted(raw_dir.rglob("*")):
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                    access = path.parent.name.upper()
                    if access not in {"PUBLIC", "EMPLOYEE", "MANAGER", "ADMIN"}:
                        access = "EMPLOYEE"
                    ingest_path(db, path, access_level=access, department="General")
        logger.info("Demo users seeded.")
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="Production-style enterprise RAG platform for role-aware knowledge access.",
    lifespan=lifespan,
)
instrument_fastapi(app)


@app.middleware("http")
async def request_metrics(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    started = perf_counter()
    REQUEST_COUNT.inc()
    try:
        response = await call_next(request)
        if response.status_code >= 500:
            ERROR_COUNT.inc()
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request completed request_id=%s method=%s path=%s status=%s latency_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            (perf_counter() - started) * 1000,
        )
        return response
    except Exception:
        ERROR_COUNT.inc()
        raise
    finally:
        REQUEST_LATENCY.observe(perf_counter() - started)


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(evaluation_router)
app.include_router(admin_router)
app.include_router(metrics_router)

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _resolve_database_url() -> str:
    url = settings.database_url
    if not url.startswith("sqlite"):
        return url

    database_path = url.replace("sqlite:///", "", 1)
    if database_path.startswith("./"):
        database_path = database_path[2:]

    path = Path(database_path)
    if not path.is_absolute():
        path = (Path(__file__).resolve().parents[2] / path).resolve()

    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


engine = create_engine(
    _resolve_database_url(),
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        columns = {column["name"] for column in inspect(engine).get_columns("documents")}
        if "content" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE documents ADD COLUMN content TEXT NOT NULL DEFAULT ''")
                )


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

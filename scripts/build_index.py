from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.database import SessionLocal, init_db
from app.services.retrieval import RetrievalService


def main() -> None:
    init_db()
    with SessionLocal() as db:
        counts = RetrievalService().build_indexes(db)
    for role, count in counts.items():
        print(f"{role}: indexed {count} authorized chunks")


if __name__ == "__main__":
    main()

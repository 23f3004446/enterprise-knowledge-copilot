from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.db.database import SessionLocal, init_db
from app.db.seed import seed_demo_users


def main() -> None:
    init_db()
    db: Session = SessionLocal()
    try:
        seed_demo_users(db)
        print("Demo users seeded successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

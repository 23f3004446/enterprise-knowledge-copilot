import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import Base
from app.db.models import User
from app.db.seed import seed_demo_users


def test_login_returns_jwt_with_required_claims(client) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "employee@example.com", "password": "demo_employee_password"},
    )
    assert response.status_code == 200
    data = response.json()
    claims = jwt.decode(data["access_token"], settings.jwt_secret_key, algorithms=["HS256"])
    assert claims["user_id"] > 0
    assert claims["username"] == "employee"
    assert claims["role"] == "EMPLOYEE"


def test_login_rejects_invalid_password(client) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "employee@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_production_seed_requires_configured_passwords(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "initial_employee_password", "")
    monkeypatch.setattr(settings, "initial_manager_password", "")
    monkeypatch.setattr(settings, "initial_admin_password", "")
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        seed_demo_users(db)
        assert db.query(User).count() == 0

    engine.dispose()


def test_production_seed_uses_configured_passwords(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "initial_employee_password", "employee-secret")
    monkeypatch.setattr(settings, "initial_manager_password", "manager-secret")
    monkeypatch.setattr(settings, "initial_admin_password", "admin-secret")
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        seed_demo_users(db)
        assert db.query(User).count() == 3
        assert all(user.hashed_password not in {"employee-secret", "manager-secret", "admin-secret"} for user in db.query(User))

    engine.dispose()

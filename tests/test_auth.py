import jwt

from app.core.config import settings


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

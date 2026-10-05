from app.core.config import settings


def get_headers(client, email: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_admin_can_upload_and_ingest_document(client, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "uploaded_documents_dir", str(tmp_path))
    response = client.post(
        "/documents/upload",
        headers=get_headers(client, "admin@example.com", "demo_admin_password"),
        files={"file": ("incident.txt", b"INC-77: Report the incident to the security team.", "text/plain")},
        data={"access_level": "ADMIN", "department": "Security"},
    )
    assert response.status_code == 201
    assert response.json()["chunks"] == 1

    admin_docs = client.get(
        "/documents",
        headers=get_headers(client, "admin@example.com", "demo_admin_password"),
    ).json()["documents"]
    assert any(doc["filename"] == "incident.txt" and doc["access_level"] == "ADMIN" for doc in admin_docs)

    employee_docs = client.get(
        "/documents",
        headers=get_headers(client, "employee@example.com", "demo_employee_password"),
    ).json()["documents"]
    assert all(doc["filename"] != "incident.txt" for doc in employee_docs)


def test_non_admin_cannot_upload(client) -> None:
    response = client.post(
        "/documents/upload",
        headers=get_headers(client, "employee@example.com", "demo_employee_password"),
        files={"file": ("note.txt", b"not authorized", "text/plain")},
    )
    assert response.status_code == 403

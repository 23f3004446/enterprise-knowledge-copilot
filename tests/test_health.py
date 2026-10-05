def test_health_endpoint_returns_ok(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "Enterprise Knowledge Copilot"


def test_root_endpoint_has_message(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Enterprise Knowledge Copilot" in response.json()["message"]

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_returns_service_status() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "caredelta-api"}


def test_local_frontend_origins_are_allowed() -> None:
    for origin in ("http://localhost:3000", "http://127.0.0.1:3000"):
        response = client.get("/health", headers={"Origin": origin})

        assert response.headers["access-control-allow-origin"] == origin

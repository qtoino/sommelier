from fastapi.testclient import TestClient

from sommelier.app import app


def test_health() -> None:
    assert TestClient(app).get("/api/health").json() == {"status": "ok"}

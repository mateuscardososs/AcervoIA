from fastapi.testclient import TestClient

from acervo_ia.main import app

client = TestClient(app)


def test_health_returns_api_status() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "acervo-ia-api"}

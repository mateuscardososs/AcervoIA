import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from acervo_ia.db import connection as db_connection
from acervo_ia.main import app

client = TestClient(app)


def test_health_returns_api_status() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "acervo-ia-api"}


def test_database_health_does_not_expose_connection_secrets(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = "SENTINEL_DATABASE_PASSWORD_DO_NOT_LOG"

    class FailingEngine:
        def connect(self) -> None:
            raise OperationalError(
                "connect",
                {},
                RuntimeError(f"password={sentinel}"),
            )

    monkeypatch.setattr(db_connection, "get_engine", lambda: FailingEngine())

    with caplog.at_level(
        logging.WARNING,
        logger="acervo_ia.api.routes.health",
    ):
        response = client.get("/health/database")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Não foi possível conectar ao banco de dados."
    }
    assert sentinel not in response.text
    assert sentinel not in caplog.text
    assert caplog.messages == ["Falha na verificação do banco de dados."]

    with pytest.raises(db_connection.DatabaseUnavailableError) as captured:
        db_connection.ping_database()

    assert captured.value.__context__ is None
    assert sentinel not in str(captured.value)


def test_database_session_sanitizes_sqlalchemy_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite://")
    monkeypatch.setattr(db_connection, "get_engine", lambda: engine)
    database_session = db_connection.get_db()
    next(database_session)

    with pytest.raises(db_connection.DatabaseUnavailableError) as captured:
        database_session.throw(
            OperationalError(
                "connect",
                {},
                RuntimeError("SENTINEL_DATABASE_PASSWORD_DO_NOT_LOG"),
            )
        )

    assert captured.value.__context__ is None
    assert "SENTINEL_DATABASE_PASSWORD_DO_NOT_LOG" not in str(captured.value)
    engine.dispose()

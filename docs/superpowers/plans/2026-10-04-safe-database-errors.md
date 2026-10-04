# Safe Database Errors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent database URLs, passwords, and connection strings from appearing in HTTP responses, application logs, or application-recorded tracebacks.

**Architecture:** The database boundary converts SQLAlchemy failures into a credential-free application exception after leaving the original `except` block, so the safe exception has no original exception context. The health route logs a constant warning without exception interpolation or `exc_info`, then returns a generic `503` response.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2, Psycopg 3, pytest, `caplog`, FastAPI `TestClient`.

## Global Constraints

- Do not read or display `.env` values.
- Do not log, interpolate, return, or otherwise expose the caught SQLAlchemy/Psycopg exception object.
- Do not use `exc_info` for database connection failures.
- Keep the client response generic.
- Preserve all existing local changes.
- Do not modify login, collection routes, models, migrations, or Alembic configuration.

---

### Task 1: Add a failing credential-leak regression test

**Files:**
- Modify: `tests/test_health.py`

**Interfaces:**
- Consumes: `acervo_ia.db.connection.get_engine`, `GET /health/database`, and the logger `acervo_ia.api.routes.health`.
- Produces: `test_database_health_does_not_expose_connection_secrets` covering response, logs, and sanitized exception context.

- [ ] **Step 1: Add the regression test**

Add these imports:

```python
import logging

import pytest
from sqlalchemy.exc import OperationalError

from acervo_ia.db import connection as db_connection
```

Add this test:

```python
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
```

- [ ] **Step 2: Run the test and verify the red state**

Run: `.venv/bin/pytest tests/test_health.py::test_database_health_does_not_expose_connection_secrets -q`

Expected: FAIL because no safe warning is recorded and `DatabaseUnavailableError` does not exist yet. The sentinel must not be printed manually while diagnosing the failure.

---

### Task 2: Sanitize database failures at the application boundary

**Files:**
- Modify: `src/acervo_ia/db/connection.py`
- Modify: `src/acervo_ia/api/routes/health.py`
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: `SQLAlchemyError` raised while creating or using the engine.
- Produces: `DatabaseUnavailableError`, `ping_database() -> None`, one constant warning, and a generic HTTP `503`.

- [ ] **Step 1: Add the safe application exception and database conversion**

Implement `src/acervo_ia/db/connection.py` as:

```python
import os
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


class DatabaseUnavailableError(RuntimeError):
    """Indicates database unavailability without exposing connection details."""


@lru_cache
def get_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise DatabaseUnavailableError("Banco de dados indisponível.")

    return create_engine(database_url, pool_pre_ping=True)


def ping_database() -> None:
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        pass
    else:
        return

    raise DatabaseUnavailableError("Banco de dados indisponível.") from None
```

The safe exception is raised after the `except` suite has ended. Do not bind the caught exception to a name, log it, interpolate it, or pass it to another object.

- [ ] **Step 2: Add constant safe logging and generic HTTP handling**

Implement `src/acervo_ia/api/routes/health.py` as:

```python
import logging

from fastapi import APIRouter, HTTPException

from acervo_ia.db.connection import DatabaseUnavailableError, ping_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", summary="Verifica se a API está respondendo")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "acervo-ia-api"}


@router.get("/health/database", summary="Verifica a conexão com o PostgreSQL")
def database_health() -> dict[str, str]:
    try:
        ping_database()
    except DatabaseUnavailableError:
        logger.warning("Falha na verificação do banco de dados.")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível conectar ao banco de dados.",
        ) from None

    return {"status": "ok", "database": "postgresql"}
```

- [ ] **Step 3: Run the focused test and verify green**

Run: `.venv/bin/pytest tests/test_health.py::test_database_health_does_not_expose_connection_secrets -q`

Expected: PASS with no sentinel in captured logs or response.

- [ ] **Step 4: Inspect the sensitive path statically**

Run:

```bash
rg -n '(logger\.|logging\.|exc_info|traceback|raise .* from|SQLAlchemyError|OperationalError)' src tests
```

Expected: the connection layer catches `SQLAlchemyError` without binding it; the route logs only the constant safe message; the HTTP exception uses `from None`; there is no `exc_info` or exception interpolation.

- [ ] **Step 5: Run final verification**

Run: `.venv/bin/pytest -q`

Run: `git diff --check`

Expected: both commands exit 0 and pytest reports no failures.

- [ ] **Step 6: Review final scope**

Run: `git status --short` and inspect diffs for `src/acervo_ia/db/connection.py`, `src/acervo_ia/api/routes/health.py`, and `tests/test_health.py`.

Expected: implementation changes are limited to safe database error conversion, safe route logging, and the regression test; existing unrelated changes remain intact.

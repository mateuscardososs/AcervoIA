from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Base, User
from acervo_ia.main import app
from acervo_ia.security import hash_password


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv(
        "AUTH_SECRET_KEY",
        "test-auth-secret-key-with-sufficient-length-0123456789",
    )
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    previous_session_factory = getattr(app.state, "test_session_factory", None)
    app.state.test_session_factory = test_session_factory

    def override_get_db() -> Iterator[Session]:
        with test_session_factory() as session:
            yield session

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        if previous_session_factory is None:
            del app.state.test_session_factory
        else:
            app.state.test_session_factory = previous_session_factory
        engine.dispose()


def create_test_user(email: str, password: str) -> UUID:
    with app.state.test_session_factory() as session:
        user = User(email=email, password_hash=hash_password(password))
        session.add(user)
        session.commit()
        user_id = user.id
    return user_id


def test_login_returns_bearer_token_and_password_is_stored_as_hash(
    auth_client: TestClient,
) -> None:
    email = "person@example.test"
    password = "correct horse battery staple"
    user_id = create_test_user(email, password)

    response = auth_client.post(
        "/auth/token",
        data={"username": email, "password": password},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]

    user = auth_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {response.json()['access_token']}"},
    )
    assert user.status_code == 200
    assert user.json() == {"id": str(user_id), "email": email}
    assert "password_hash" not in user.json()


def test_invalid_login_uses_same_generic_response(
    auth_client: TestClient,
) -> None:
    email = "person@example.test"
    create_test_user(email, "correct horse battery staple")

    unknown_email = auth_client.post(
        "/auth/token",
        data={"username": "missing@example.test", "password": "wrong"},
    )
    wrong_password = auth_client.post(
        "/auth/token",
        data={"username": email, "password": "wrong"},
    )

    assert unknown_email.status_code == wrong_password.status_code == 401
    assert unknown_email.json() == wrong_password.json()
    assert unknown_email.json() == {"detail": "E-mail ou senha incorretos."}


def test_authenticated_route_rejects_missing_bearer_token(
    auth_client: TestClient,
) -> None:
    response = auth_client.get("/auth/me")

    assert response.status_code == 401


def test_authenticated_route_rejects_invalid_bearer_token(
    auth_client: TestClient,
) -> None:
    response = auth_client.get(
        "/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Não foi possível validar as credenciais."
    }


def test_password_hash_is_not_the_plaintext(
    auth_client: TestClient,
) -> None:
    password = "a test password"
    user_id = create_test_user("hash@example.test", password)

    with auth_client.app.state.test_session_factory() as session:
        user = session.scalar(select(User).where(User.id == user_id))

    assert user is not None
    assert user.password_hash != password
    assert user.password_hash.startswith("$argon2")

from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Base, Collection, User
from acervo_ia.main import app
from acervo_ia.security import create_access_token, hash_password


@pytest.fixture
def collections_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
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


def create_user_and_token(email: str) -> tuple[UUID, str]:
    with app.state.test_session_factory() as session:
        user = User(
            email=email,
            password_hash=hash_password("collection-test-password"),
        )
        session.add(user)
        session.commit()
        user_id = user.id
    return user_id, create_access_token(str(user_id))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_collection_crud_uses_authenticated_owner(
    collections_client: TestClient,
) -> None:
    client = collections_client
    owner_id, token = create_user_and_token("owner@example.test")
    headers = bearer(token)

    created = client.post(
        "/collections",
        json={
            "name": "Manuais",
            "description": "Documentos de referência",
            "owner_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=headers,
    )
    assert created.status_code == 422

    created = client.post(
        "/collections",
        json={"name": "Manuais", "description": "Documentos de referência"},
        headers=headers,
    )
    assert created.status_code == 201
    collection = created.json()
    collection_id = collection["id"]
    assert collection["name"] == "Manuais"
    assert collection["description"] == "Documentos de referência"
    assert "owner_id" not in collection

    listed = client.get("/collections", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [collection_id]

    retrieved = client.get(f"/collections/{collection_id}", headers=headers)
    assert retrieved.status_code == 200
    assert retrieved.json() == collection

    updated = client.patch(
        f"/collections/{collection_id}",
        json={"name": "Manuais atualizados", "description": None},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Manuais atualizados"
    assert updated.json()["description"] is None

    with app.state.test_session_factory() as session:
        stored = session.scalar(
            select(Collection).where(Collection.id == UUID(collection_id))
        )
    assert stored is not None
    assert stored.owner_id == owner_id
    assert stored.name == "Manuais atualizados"

    deleted = client.delete(f"/collections/{collection_id}", headers=headers)
    assert deleted.status_code == 204
    assert deleted.content == b""
    missing = client.get(f"/collections/{collection_id}", headers=headers)
    assert missing.status_code == 404


def test_collection_list_is_isolated_between_users(
    collections_client: TestClient,
) -> None:
    client = collections_client
    _, first_token = create_user_and_token("first@example.test")
    _, second_token = create_user_and_token("second@example.test")

    first_created = client.post(
        "/collections",
        json={"name": "Privada do primeiro"},
        headers=bearer(first_token),
    )
    second_created = client.post(
        "/collections",
        json={"name": "Privada do segundo"},
        headers=bearer(second_token),
    )

    assert first_created.status_code == second_created.status_code == 201
    first_list = client.get("/collections", headers=bearer(first_token))
    second_list = client.get("/collections", headers=bearer(second_token))
    assert [item["name"] for item in first_list.json()] == ["Privada do primeiro"]
    assert [item["name"] for item in second_list.json()] == ["Privada do segundo"]


@pytest.mark.parametrize(
    "method,payload",
    [
        ("get", None),
        ("patch", {"name": "Invadida"}),
        ("delete", None),
    ],
)
def test_collection_cannot_be_accessed_by_another_user(
    collections_client: TestClient,
    method: str,
    payload: dict[str, str] | None,
) -> None:
    client = collections_client
    _, owner_token = create_user_and_token("owner@example.test")
    _, other_token = create_user_and_token("other@example.test")
    created = client.post(
        "/collections",
        json={"name": "Privada"},
        headers=bearer(owner_token),
    )
    collection_id = created.json()["id"]

    response = getattr(client, method)(
        f"/collections/{collection_id}",
        headers=bearer(other_token),
        **({"json": payload} if payload is not None else {}),
    )

    assert response.status_code == 404
    owner_view = client.get(
        f"/collections/{collection_id}",
        headers=bearer(owner_token),
    )
    assert owner_view.status_code == 200
    assert owner_view.json()["name"] == "Privada"


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/collections", {"name": "Sem token"}),
        ("get", "/collections", None),
        ("get", "/collections/00000000-0000-0000-0000-000000000001", None),
        (
            "patch",
            "/collections/00000000-0000-0000-0000-000000000001",
            {"name": "Sem token"},
        ),
        ("delete", "/collections/00000000-0000-0000-0000-000000000001", None),
    ],
)
def test_all_collection_operations_require_authentication(
    collections_client: TestClient,
    method: str,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    response = getattr(collections_client, method)(
        path,
        **({"json": payload} if payload is not None else {}),
    )

    assert response.status_code == 401


def test_duplicate_collection_name_for_same_owner_returns_conflict(
    collections_client: TestClient,
) -> None:
    _, token = create_user_and_token("owner@example.test")
    headers = bearer(token)
    first = collections_client.post(
        "/collections",
        json={"name": "Mesmo nome"},
        headers=headers,
    )
    duplicate = collections_client.post(
        "/collections",
        json={"name": "Mesmo nome"},
        headers=headers,
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Já existe uma coleção com este nome."}

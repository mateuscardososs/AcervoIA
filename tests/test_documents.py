from collections.abc import Iterator
from io import BytesIO
from pathlib import Path
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from acervo_ia.api.routes import documents
from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Base, Collection, Document, User
from acervo_ia.main import app
from acervo_ia.security import create_access_token


@pytest.fixture
def document_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[TestClient]:
    monkeypatch.setenv(
        "AUTH_SECRET_KEY",
        "test-auth-secret-key-with-sufficient-length-0123456789",
    )
    monkeypatch.setattr(
        documents,
        "DOCUMENT_STORAGE_DIRECTORY",
        tmp_path / "stored",
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


def create_user_and_collection(email: str) -> tuple[UUID, UUID, str]:
    with app.state.test_session_factory() as session:
        user = User(email=email, password_hash="not-used-by-bearer-auth")
        session.add(user)
        session.flush()
        collection = Collection(owner_id=user.id, name=f"Coleção de {email}")
        session.add(collection)
        session.commit()
        user_id = user.id
        collection_id = collection.id
    return user_id, collection_id, create_access_token(str(user_id))


def docx_bytes() -> bytes:
    content = BytesIO()
    with ZipFile(content, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    return content.getvalue()


@pytest.mark.parametrize(
    "filename,content,content_type",
    [
        ("../../outside.txt", b"Texto de teste", "text/plain"),
        ("manual.pdf", b"%PDF-1.7\nconteudo", "application/pdf"),
        (
            "manual.docx",
            docx_bytes(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ],
)
def test_upload_lists_and_deletes_document(
    document_client: TestClient,
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    client = document_client
    _, collection_id, token = create_user_and_collection("owner@example.test")
    headers = {"Authorization": f"Bearer {token}"}

    uploaded = client.post(
        f"/collections/{collection_id}/documents",
        files={"file": (filename, content, content_type)},
        headers=headers,
    )

    assert uploaded.status_code == 201
    metadata = uploaded.json()
    assert metadata["original_filename"] == filename
    assert metadata["content_type"] == content_type
    assert metadata["size_bytes"] == len(content)
    document_id = metadata["id"]

    with app.state.test_session_factory() as session:
        stored = session.scalar(
            select(Document).where(Document.id == UUID(document_id))
        )
    assert stored is not None
    assert stored.collection_id == collection_id
    stored_path = documents.DOCUMENT_STORAGE_DIRECTORY / stored.storage_key
    assert stored_path.is_file()
    assert stored_path.name != filename
    assert stored_path.parent == documents.DOCUMENT_STORAGE_DIRECTORY
    assert stored_path.read_bytes() == content

    listed = client.get(
        f"/collections/{collection_id}/documents",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json() == [metadata]

    deleted = client.delete(
        f"/collections/{collection_id}/documents/{document_id}",
        headers=headers,
    )
    assert deleted.status_code == 204
    assert not stored_path.exists()
    with app.state.test_session_factory() as session:
        assert session.get(Document, UUID(document_id)) is None


@pytest.mark.parametrize(
    "filename,content",
    [
        ("manual.exe", b"%PDF-1.7"),
        ("manual.pdf", b"not a PDF"),
        ("manual.docx", b"not a DOCX archive"),
        ("manual.txt", b"\xff invalid utf-8"),
    ],
)
def test_upload_rejects_invalid_file(
    document_client: TestClient,
    filename: str,
    content: bytes,
) -> None:
    _, collection_id, token = create_user_and_collection("owner@example.test")
    response = document_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": (filename, content)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "O arquivo não é válido ou não é aceito."}


def test_upload_rejects_files_over_configured_size_limit(
    document_client: TestClient,
) -> None:
    from acervo_ia.config import MAX_DOCUMENT_SIZE_BYTES

    _, collection_id, token = create_user_and_collection("owner@example.test")
    response = document_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("large.txt", b"a" * (MAX_DOCUMENT_SIZE_BYTES + 1))},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "O arquivo excede o limite permitido."}


def test_storage_key_collision_does_not_delete_existing_file(
    document_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, token = create_user_and_collection("owner@example.test")
    storage_key = "a" * 32
    documents.DOCUMENT_STORAGE_DIRECTORY.mkdir(parents=True)
    existing_file = documents.DOCUMENT_STORAGE_DIRECTORY / storage_key
    existing_file.write_bytes(b"existing data")
    monkeypatch.setattr(documents, "uuid4", lambda: UUID(hex=storage_key))

    response = document_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("new.txt", b"new data", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 500
    assert existing_file.read_bytes() == b"existing data"


def test_document_operations_are_scoped_to_collection_owner(
    document_client: TestClient,
) -> None:
    client = document_client
    _, collection_id, owner_token = create_user_and_collection("owner@example.test")
    _, other_collection_id, other_token = create_user_and_collection(
        "other@example.test"
    )
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}
    uploaded = client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("private.txt", b"segredo", "text/plain")},
        headers=owner_headers,
    )
    document_id = uploaded.json()["id"]

    foreign_list = client.get(
        f"/collections/{collection_id}/documents",
        headers=other_headers,
    )
    foreign_upload = client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("other.txt", b"nao autorizado", "text/plain")},
        headers=other_headers,
    )
    foreign_delete = client.delete(
        f"/collections/{collection_id}/documents/{document_id}",
        headers=other_headers,
    )

    assert foreign_list.status_code == 404
    assert foreign_upload.status_code == 404
    assert foreign_delete.status_code == 404
    assert client.get(
        f"/collections/{other_collection_id}/documents",
        headers=other_headers,
    ).json() == []
    assert client.get(
        f"/collections/{collection_id}/documents",
        headers=owner_headers,
    ).json()[0]["id"] == document_id

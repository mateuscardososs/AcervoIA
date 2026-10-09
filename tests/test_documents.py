from collections.abc import Iterator
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
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


def create_stored_document(
    collection_id: UUID,
    filename: str,
    content: bytes,
    content_type: str,
) -> tuple[UUID, str]:
    storage_key = uuid4().hex
    path = documents.DOCUMENT_STORAGE_DIRECTORY / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with app.state.test_session_factory() as session:
        record = Document(
            collection_id=collection_id,
            original_filename=filename,
            storage_key=storage_key,
            content_type=content_type,
            size_bytes=len(content),
        )
        session.add(record)
        session.commit()
        return record.id, storage_key


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


def test_upload_same_content_to_same_collection_reuses_document_and_file(
    document_client: TestClient,
) -> None:
    _, collection_id, token = create_user_and_collection("dedupe@example.test")
    headers = {"Authorization": f"Bearer {token}"}
    content = b"Identical document bytes"

    first = document_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("first.txt", content, "text/plain")},
        headers=headers,
    )
    second = document_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("renamed.txt", content, "text/plain")},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["original_filename"] == "first.txt"
    with app.state.test_session_factory() as session:
        stored = session.scalars(
            select(Document).where(Document.collection_id == collection_id)
        ).all()
        assert len(stored) == 1
        assert stored[0].content_sha256 == sha256(content).hexdigest()
    assert len(list(documents.DOCUMENT_STORAGE_DIRECTORY.iterdir())) == 1


def test_upload_different_content_to_same_collection_creates_another_document(
    document_client: TestClient,
) -> None:
    _, collection_id, token = create_user_and_collection("different@example.test")
    headers = {"Authorization": f"Bearer {token}"}

    first = document_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("first.txt", b"First content", "text/plain")},
        headers=headers,
    )
    second = document_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("second.txt", b"Second content", "text/plain")},
        headers=headers,
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    with app.state.test_session_factory() as session:
        stored = session.scalars(
            select(Document).where(Document.collection_id == collection_id)
        ).all()
    assert len(stored) == 2
    assert len({document.content_sha256 for document in stored}) == 2


def test_upload_same_content_to_different_users_is_not_shared(
    document_client: TestClient,
) -> None:
    _, first_collection, first_token = create_user_and_collection(
        "first-owner@example.test"
    )
    _, second_collection, second_token = create_user_and_collection(
        "second-owner@example.test"
    )
    content = b"Same bytes, separate collection ownership"

    first = document_client.post(
        f"/collections/{first_collection}/documents",
        files={"file": ("manual.txt", content, "text/plain")},
        headers={"Authorization": f"Bearer {first_token}"},
    )
    second = document_client.post(
        f"/collections/{second_collection}/documents",
        files={"file": ("manual.txt", content, "text/plain")},
        headers={"Authorization": f"Bearer {second_token}"},
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert len(list(documents.DOCUMENT_STORAGE_DIRECTORY.iterdir())) == 2
    assert [item["id"] for item in document_client.get(
        f"/collections/{first_collection}/documents",
        headers={"Authorization": f"Bearer {first_token}"},
    ).json()] == [first.json()["id"]]
    assert [item["id"] for item in document_client.get(
        f"/collections/{second_collection}/documents",
        headers={"Authorization": f"Bearer {second_token}"},
    ).json()] == [second.json()["id"]]


def test_upload_duplicate_of_legacy_document_backfills_its_content_hash(
    document_client: TestClient,
) -> None:
    _, collection_id, token = create_user_and_collection("legacy@example.test")
    content = b"Existing document without a hash"
    storage_key = "b" * 32
    (documents.DOCUMENT_STORAGE_DIRECTORY).mkdir(parents=True, exist_ok=True)
    (documents.DOCUMENT_STORAGE_DIRECTORY / storage_key).write_bytes(content)
    with app.state.test_session_factory() as session:
        existing = Document(
            collection_id=collection_id,
            original_filename="legacy.txt",
            storage_key=storage_key,
            content_type="text/plain",
            size_bytes=len(content),
            content_sha256=None,
        )
        session.add(existing)
        session.commit()
        existing_id = existing.id

    response = document_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("new-name.txt", content, "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(existing_id)
    with app.state.test_session_factory() as session:
        backfilled = session.get(Document, existing_id)
        assert backfilled is not None
        assert len(backfilled.content_sha256) == 64
    assert len(list(documents.DOCUMENT_STORAGE_DIRECTORY.iterdir())) == 1


def test_concurrent_duplicate_insert_returns_winner_and_removes_losing_file(
    document_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, token = create_user_and_collection("race@example.test")
    headers = {"Authorization": f"Bearer {token}"}
    content = b"Concurrent identical content"
    winner = document_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("winner.txt", content, "text/plain")},
        headers=headers,
    )
    real_lookup = getattr(documents, "_find_document_by_content_hash", None)
    assert real_lookup is not None
    lookup_calls = 0

    def miss_first_lookup(session: Session, scoped_collection_id: UUID, digest: str):
        nonlocal lookup_calls
        lookup_calls += 1
        if lookup_calls == 1:
            return None
        return real_lookup(session, scoped_collection_id, digest)

    monkeypatch.setattr(
        documents,
        "_find_document_by_content_hash",
        miss_first_lookup,
    )
    losing_race = document_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("racer.txt", content, "text/plain")},
        headers=headers,
    )

    assert winner.status_code == 201
    assert losing_race.status_code == 200
    assert losing_race.json()["id"] == winner.json()["id"]
    assert lookup_calls == 2
    assert len(list(documents.DOCUMENT_STORAGE_DIRECTORY.iterdir())) == 1


def test_database_failure_does_not_leave_uploaded_file_or_document(
    document_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    _, collection_id, token = create_user_and_collection("db-failure@example.test")

    def fail_commit(_session: Session) -> None:
        raise SQLAlchemyError("private database connection details")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = document_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("failed.txt", b"temporary file", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert "private database" not in response.text
    assert not documents.DOCUMENT_STORAGE_DIRECTORY.exists() or not list(
        documents.DOCUMENT_STORAGE_DIRECTORY.iterdir()
    )
    with app.state.test_session_factory() as session:
        assert session.scalar(select(Document)) is None


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


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "disposition"),
    [
        ("manual.pdf", b"%PDF-1.7\nconteudo", "application/pdf", "inline"),
        (
            "manual.docx",
            docx_bytes(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "attachment",
        ),
        ("manual.txt", b"texto original", "text/plain", "attachment"),
    ],
)
def test_owner_can_open_original_document_with_safe_disposition(
    document_client: TestClient,
    filename: str,
    content: bytes,
    content_type: str,
    disposition: str,
) -> None:
    _, collection_id, token = create_user_and_collection("file-owner@example.test")
    document_id, storage_key = create_stored_document(
        collection_id,
        filename,
        content,
        content_type,
    )

    response = document_client.get(
        f"/collections/{collection_id}/documents/{document_id}/file",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith(content_type)
    assert response.headers["content-disposition"].startswith(disposition)
    assert storage_key.encode() not in response.content


def test_original_file_requires_authentication_and_hides_cross_user_documents(
    document_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, _ = create_user_and_collection("file-owner@example.test")
    _, _, other_token = create_user_and_collection("file-other@example.test")
    document_id, _ = create_stored_document(
        collection_id,
        "private.txt",
        b"private bytes",
        "text/plain",
    )

    def path_must_not_be_resolved(_storage_key: str):
        pytest.fail("O caminho foi resolvido antes da validação da coleção")

    monkeypatch.setattr(documents, "_safe_storage_path", path_must_not_be_resolved)
    unauthenticated = document_client.get(
        f"/collections/{collection_id}/documents/{document_id}/file"
    )
    foreign = document_client.get(
        f"/collections/{collection_id}/documents/{document_id}/file",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert unauthenticated.status_code == 401
    assert foreign.status_code == 404


def test_document_cannot_be_opened_through_a_different_collection(
    document_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, first_collection, token = create_user_and_collection(
        "same-owner@example.test"
    )
    with app.state.test_session_factory() as session:
        second_collection = Collection(owner_id=user_id, name="Outra coleção")
        session.add(second_collection)
        session.commit()
        second_collection_id = second_collection.id
    document_id, _ = create_stored_document(
        first_collection,
        "private.txt",
        b"private bytes",
        "text/plain",
    )

    def path_must_not_be_resolved(_storage_key: str):
        pytest.fail("O arquivo de outra coleção foi resolvido")

    monkeypatch.setattr(documents, "_safe_storage_path", path_must_not_be_resolved)
    response = document_client.get(
        f"/collections/{second_collection_id}/documents/{document_id}/file",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


def test_missing_collection_or_document_returns_not_found_before_path_lookup(
    document_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, token = create_user_and_collection("missing-source@example.test")
    document_id, _ = create_stored_document(
        collection_id,
        "private.txt",
        b"private bytes",
        "text/plain",
    )

    def path_must_not_be_resolved(_storage_key: str):
        pytest.fail("Um recurso inexistente teve o caminho resolvido")

    monkeypatch.setattr(documents, "_safe_storage_path", path_must_not_be_resolved)
    headers = {"Authorization": f"Bearer {token}"}
    missing_document = document_client.get(
        f"/collections/{collection_id}/documents/{uuid4()}/file",
        headers=headers,
    )
    missing_collection = document_client.get(
        f"/collections/{uuid4()}/documents/{document_id}/file",
        headers=headers,
    )

    assert missing_document.status_code == 404
    assert missing_collection.status_code == 404


def test_missing_original_file_returns_safe_not_found_message(
    document_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, collection_id, token = create_user_and_collection("missing-file@example.test")
    document_id, storage_key = create_stored_document(
        collection_id,
        "missing.txt",
        b"will be removed",
        "text/plain",
    )
    (documents.DOCUMENT_STORAGE_DIRECTORY / storage_key).unlink()

    response = document_client.get(
        f"/collections/{collection_id}/documents/{document_id}/file",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "O arquivo original deste documento não está disponível."
    }
    assert str(documents.DOCUMENT_STORAGE_DIRECTORY) not in response.text
    assert str(documents.DOCUMENT_STORAGE_DIRECTORY) not in caplog.text

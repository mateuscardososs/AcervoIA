from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from acervo_ia import config
from acervo_ia.db.connection import get_db
from acervo_ia.db.models import (
    Base,
    Collection,
    Document,
    DocumentChunk,
    DocumentTask,
    User,
)
from acervo_ia.main import app
from acervo_ia.security import create_access_token
from acervo_ia.services import embeddings as embedding_service
from acervo_ia.worker import run_task


@pytest.fixture
def task_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    monkeypatch.setenv(
        "AUTH_SECRET_KEY",
        "test-auth-secret-key-with-sufficient-length-0123456789",
    )
    monkeypatch.setattr(config, "DOCUMENT_STORAGE_DIRECTORY", tmp_path / "stored")
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    old_factory = getattr(app.state, "test_session_factory", None)
    app.state.test_session_factory = factory

    def override_get_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    old_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        if old_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = old_override
        if old_factory is None:
            del app.state.test_session_factory
        else:
            app.state.test_session_factory = old_factory
        engine.dispose()


def owned_document(email: str, *, content: bytes = b"Trecho seguro para indexacao") -> tuple[UUID, UUID, UUID, str]:
    with app.state.test_session_factory() as session:
        user = User(email=email, password_hash="unused")
        session.add(user)
        session.flush()
        collection = Collection(owner_id=user.id, name=f"Acervo {email}")
        session.add(collection)
        session.flush()
        key = uuid4().hex
        path = config.DOCUMENT_STORAGE_DIRECTORY / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        document = Document(
            collection_id=collection.id,
            original_filename="manual.txt",
            storage_key=key,
            content_type="text/plain",
            size_bytes=len(content),
        )
        session.add(document)
        session.commit()
        return user.id, collection.id, document.id, create_access_token(str(user.id))


def start_task(client: TestClient, collection_id: UUID, document_id: UUID, token: str, kind: str):
    suffix = "process" if kind == "process" else "embeddings"
    response = client.post(
        f"/collections/{collection_id}/documents/{document_id}/{suffix}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 202
    return response.json()


def test_processing_is_enqueued_then_worker_completes_idempotently(task_client: TestClient) -> None:
    _, collection_id, document_id, token = owned_document("processing@example.test")
    task = start_task(task_client, collection_id, document_id, token, "process")
    assert task["status"] == "pending"
    assert task["progress"] == 0

    run_task(task["id"], session_factory=app.state.test_session_factory)
    status = task_client.get(
        f"/collections/{collection_id}/documents/{document_id}/tasks/{task['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["progress"] == 100
    with app.state.test_session_factory() as session:
        chunks = session.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
    assert len(chunks) == 1


def test_duplicate_start_reuses_the_existing_active_task(task_client: TestClient) -> None:
    _, collection_id, document_id, token = owned_document("duplicate-task@example.test")
    first = start_task(task_client, collection_id, document_id, token, "process")
    second = start_task(task_client, collection_id, document_id, token, "process")
    assert first["id"] == second["id"]
    with app.state.test_session_factory() as session:
        tasks = session.scalars(
            select(DocumentTask).where(DocumentTask.document_id == document_id)
        ).all()
    assert len(tasks) == 1


def test_embedding_failure_retries_with_bounded_attempts_and_no_duplicate_chunks(
    task_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, collection_id, document_id, token = owned_document("retry@example.test")
    process = start_task(task_client, collection_id, document_id, token, "process")
    run_task(process["id"], session_factory=app.state.test_session_factory)
    calls = 0

    def flaky(_texts: list[str], *, model: str | None = None) -> list[list[float]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise embedding_service.EmbeddingServiceError("provider secret detail")
        return [[0.0] * config.EMBEDDING_DIMENSIONS]

    from acervo_ia import worker

    monkeypatch.setattr(worker, "generate_embeddings", flaky)
    embed = start_task(task_client, collection_id, document_id, token, "embeddings")
    run_task(embed["id"], session_factory=app.state.test_session_factory)
    with app.state.test_session_factory() as session:
        first = session.get(DocumentTask, UUID(embed["id"]))
        assert first is not None
        assert first.status == "pending"
        assert first.attempt_count == 1
        assert session.scalar(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ) is not None

    run_task(embed["id"], session_factory=app.state.test_session_factory)
    status = task_client.get(
        f"/collections/{collection_id}/documents/{document_id}/tasks/{embed['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status.json()["status"] == "completed"
    with app.state.test_session_factory() as session:
        chunks = session.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
    assert len(chunks) == 1
    assert chunks[0].embedding_model == config.OLLAMA_EMBEDDING_MODEL


def test_embedding_retry_stops_after_three_attempts_without_leaking_logs(
    task_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, collection_id, document_id, token = owned_document("retry-limit@example.test")
    process = start_task(task_client, collection_id, document_id, token, "process")
    run_task(process["id"], session_factory=app.state.test_session_factory)
    from acervo_ia import worker

    monkeypatch.setattr(
        worker,
        "generate_embeddings",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            embedding_service.EmbeddingServiceError("private provider credential")
        ),
    )
    embed = start_task(task_client, collection_id, document_id, token, "embeddings")
    for _ in range(3):
        run_task(embed["id"], session_factory=app.state.test_session_factory)

    status = task_client.get(
        f"/collections/{collection_id}/documents/{document_id}/tasks/{embed['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status.json()["status"] == "failed"
    assert status.json()["attempt_count"] == 3
    assert "private provider credential" not in status.text
    assert "private provider credential" not in caplog.text


def test_reprocessing_replaces_chunks_instead_of_duplicating_them(
    task_client: TestClient,
) -> None:
    _, collection_id, document_id, token = owned_document(
        "reprocess-queue@example.test", content=b"First extracted content"
    )
    first = start_task(task_client, collection_id, document_id, token, "process")
    run_task(first["id"], session_factory=app.state.test_session_factory)
    with app.state.test_session_factory() as session:
        document = session.get(Document, document_id)
        assert document is not None
        (config.DOCUMENT_STORAGE_DIRECTORY / document.storage_key).write_bytes(
            b"Replacement extracted content"
        )
    second = start_task(task_client, collection_id, document_id, token, "process")
    run_task(second["id"], session_factory=app.state.test_session_factory)
    with app.state.test_session_factory() as session:
        chunks = session.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
    assert len(chunks) == 1
    assert chunks[0].content == "Replacement extracted content"


def test_failed_extraction_is_terminal_and_does_not_leak_internal_error(
    task_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from acervo_ia import worker

    _, collection_id, document_id, token = owned_document("failure@example.test", content=b" ")
    task = start_task(task_client, collection_id, document_id, token, "process")
    monkeypatch.setattr(
        worker,
        "extract_document_pages",
        lambda *_args: (_ for _ in ()).throw(worker.DocumentExtractionError("/private/path")),
    )
    run_task(task["id"], session_factory=app.state.test_session_factory)
    response = task_client.get(
        f"/collections/{collection_id}/documents/{document_id}/tasks/{task['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "/private/path" not in response.text


def test_task_status_and_worker_require_matching_owned_document(
    task_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, collection_id, document_id, owner_token = owned_document("owner@example.test")
    task = start_task(task_client, collection_id, document_id, owner_token, "process")
    with app.state.test_session_factory() as session:
        stranger = User(email="stranger@example.test", password_hash="unused")
        session.add(stranger)
        session.commit()
        stranger_token = create_access_token(str(stranger.id))

    response = task_client.get(
        f"/collections/{collection_id}/documents/{document_id}/tasks/{task['id']}",
        headers={"Authorization": f"Bearer {stranger_token}"},
    )
    assert response.status_code == 404

    from acervo_ia.db.models import DocumentTask

    with app.state.test_session_factory() as session:
        queued = session.get(DocumentTask, UUID(task["id"]))
        assert queued is not None
        queued.owner_id = UUID(int=999)
        session.commit()
    from acervo_ia import worker

    monkeypatch.setattr(
        worker,
        "_safe_storage_path",
        lambda _key: pytest.fail("worker accessed the file before validating ownership"),
    )
    run_task(task["id"], session_factory=app.state.test_session_factory)
    with app.state.test_session_factory() as session:
        queued = session.get(DocumentTask, UUID(task["id"]))
        assert queued is not None
        assert queued.status == "failed"


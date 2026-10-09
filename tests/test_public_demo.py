from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from acervo_ia import config
from acervo_ia.db.connection import get_db
from acervo_ia.db.models import (
    Base,
    Collection,
    QuestionHistory,
    Document,
    RuntimeSetting,
    UsageBucket,
    User,
)
from acervo_ia.security import create_access_token
from acervo_ia.services.usage_limits import _consume
from acervo_ia.main import app


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("AUTH_SECRET_KEY", "test-auth-secret-key-with-sufficient-length-0123456789")
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    old_factory = getattr(app.state, "test_session_factory", None)
    app.state.test_session_factory = factory

    def override_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    old_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
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


def _make_demo_user() -> tuple[UUID, UUID]:
    with app.state.test_session_factory() as session:
        user = User(email="public-demo@example.test", password_hash="random", is_demo=True)
        session.add(user)
        session.flush()
        collection = Collection(owner_id=user.id, name=config.DEMO_COLLECTION_NAME)
        session.add(collection)
        session.flush()
        session.add(
            Document(
                collection_id=collection.id,
                original_filename="[DEMO FICTÍCIO] exemplo.txt",
                storage_key=uuid4().hex,
                content_type="text/plain",
                size_bytes=1,
            )
        )
        session.merge(RuntimeSetting(key="public_demo_enabled", value="true"))
        session.commit()
        return user.id, collection.id


def test_demo_session_is_short_lived_and_only_when_enabled(
    auth_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(config, "DEMO_ENABLED", False)
    assert auth_client.post("/auth/demo-session").status_code == 404

    _make_demo_user()
    monkeypatch.setattr(config, "DEMO_ENABLED", True)
    response = auth_client.post("/auth/demo-session")
    assert response.status_code == 200
    token = response.json()["access_token"]
    identity = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert identity.status_code == 200
    assert identity.json()["is_demo"] is True
    assert identity.json()["email"] == "public-demo@example.test"


def test_demo_switch_disables_existing_demo_tokens(
    auth_client: TestClient, monkeypatch
) -> None:
    user_id, collection_id = _make_demo_user()
    monkeypatch.setattr(config, "DEMO_ENABLED", True)
    token = create_access_token(str(user_id))
    monkeypatch.setattr(config, "DEMO_ENABLED", False)

    response = auth_client.post(
        f"/collections/{collection_id}/ask",
        json={"question": "Pergunta fictícia", "strategy": "text"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    with app.state.test_session_factory() as session:
        assert session.scalar(select(UsageBucket.id)) is None


def test_demo_account_is_read_only_at_the_api(
    auth_client: TestClient, monkeypatch
) -> None:
    user_id, collection_id = _make_demo_user()
    monkeypatch.setattr(config, "DEMO_ENABLED", True)
    monkeypatch.setattr(config, "DEMO_ENABLED", True)
    token = create_access_token(str(user_id))
    headers = {"Authorization": f"Bearer {token}"}

    created = auth_client.post("/collections", json={"name": "attempt"}, headers=headers)
    changed = auth_client.patch(
        f"/collections/{collection_id}",
        json={"name": "altered"},
        headers=headers,
    )
    deleted = auth_client.delete(f"/collections/{collection_id}", headers=headers)
    assert [created.status_code, changed.status_code, deleted.status_code] == [403, 403, 403]

    document_id = "00000000-0000-0000-0000-000000000111"
    uploaded = auth_client.post(
        f"/collections/{collection_id}/documents",
        files={"file": ("manual.txt", b"fictitious", "text/plain")},
        headers=headers,
    )
    removed = auth_client.delete(
        f"/collections/{collection_id}/documents/{document_id}", headers=headers
    )
    processed = auth_client.post(
        f"/collections/{collection_id}/documents/{document_id}/process", headers=headers
    )
    embedded = auth_client.post(
        f"/collections/{collection_id}/documents/{document_id}/embeddings", headers=headers
    )
    assert [uploaded.status_code, removed.status_code, processed.status_code, embedded.status_code] == [403] * 4


def test_demo_questions_are_limited_and_not_persisted_in_history(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from acervo_ia.services import question_answering
    from acervo_ia.services.question_answering import AnswerResult, NO_EVIDENCE_ANSWER

    user_id, collection_id = _make_demo_user()
    monkeypatch.setattr(config, "DEMO_ENABLED", True)
    monkeypatch.setattr(config, "DEMO_QUESTION_LIMIT_PER_IP", 1)
    monkeypatch.setattr(
        question_answering,
        "answer_question",
        lambda *_args, **_kwargs: AnswerResult(NO_EVIDENCE_ANSWER, (), ()),
    )
    token = create_access_token(str(user_id))
    headers = {"Authorization": f"Bearer {token}"}
    path = f"/collections/{collection_id}/ask"
    first = auth_client.post(path, json={"question": "Pergunta fictícia", "strategy": "text"}, headers=headers)
    second = auth_client.post(path, json={"question": "Outra pergunta", "strategy": "text"}, headers=headers)

    assert first.status_code == 200
    assert first.json()["sources"] == []
    assert second.status_code == 429
    history = auth_client.get(f"/collections/{collection_id}/history", headers=headers)
    assert history.status_code == 200
    assert history.json()["items"] == []
    with app.state.test_session_factory() as session:
        assert session.scalar(select(QuestionHistory.id)) is None


def test_demo_login_limit_is_shared_and_persisted(
    auth_client: TestClient, monkeypatch
) -> None:
    _make_demo_user()
    monkeypatch.setattr(config, "DEMO_ENABLED", True)
    monkeypatch.setattr(config, "DEMO_LOGIN_LIMIT_PER_IP", 1)
    assert auth_client.post("/auth/demo-session").status_code == 200
    limited = auth_client.post("/auth/demo-session")
    assert limited.status_code == 429
    assert "limite" in limited.json()["detail"].lower()
    with app.state.test_session_factory() as session:
        assert session.scalar(select(UsageBucket.count)) == 1


def test_atomic_usage_bucket_enforces_limit_under_concurrent_requests(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from datetime import UTC, datetime
    from fastapi import HTTPException

    monkeypatch.setenv("AUTH_SECRET_KEY", "test-auth-secret-key-with-sufficient-length-0123456789")
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'limits.sqlite'}",
        connect_args={"timeout": 20},
    )
    Base.metadata.create_all(engine)
    start = datetime(2026, 10, 9, tzinfo=UTC)

    def reserve() -> int:
        with Session(engine) as session:
            try:
                _consume(session, "concurrent_test", "opaque-client-key", start, 3)
                return 1
            except HTTPException as error:
                assert error.status_code == 429
                return 0

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: reserve(), range(12)))
    with Session(engine) as session:
        count = session.scalar(select(UsageBucket.count))
    engine.dispose()
    assert sum(results) == 3
    assert count == 3

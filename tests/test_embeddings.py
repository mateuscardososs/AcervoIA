from collections.abc import Iterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Base, Collection, Document, DocumentChunk, User
from acervo_ia.main import app
from acervo_ia.api.routes import embeddings as embedding_routes
from acervo_ia.security import create_access_token
from acervo_ia.services import embeddings as embedding_service
from acervo_ia.services import semantic_search


@pytest.fixture
def embeddings_client(
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
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    previous_factory = getattr(app.state, "test_session_factory", None)
    app.state.test_session_factory = factory

    def override_get_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        if previous_factory is None:
            del app.state.test_session_factory
        else:
            app.state.test_session_factory = previous_factory
        engine.dispose()


def create_owned_document(email: str = "owner@example.test") -> tuple[
    UUID, UUID, UUID, str
]:
    with app.state.test_session_factory() as session:
        user = User(email=email, password_hash="unused")
        session.add(user)
        session.flush()
        collection = Collection(owner_id=user.id, name=f"Coleção {email}")
        session.add(collection)
        session.flush()
        document = Document(
            collection_id=collection.id,
            original_filename="manual.txt",
            storage_key="a" * 32,
            content_type="text/plain",
            size_bytes=100,
            processing_status="completed",
        )
        session.add(document)
        session.flush()
        chunks = [
            DocumentChunk(document_id=document.id, position=i, content=f"Trecho {i}")
            for i in range(2)
        ]
        session.add_all(chunks)
        session.commit()
        return (
            user.id,
            collection.id,
            document.id,
            create_access_token(str(user.id)),
        )


def mocked_ollama(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: dict[str, Any] | None = None,
    failure: Exception | None = None,
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        requests.append(json.loads(request.content))
        if failure is not None:
            raise failure
        return httpx.Response(200, json=response or {"embeddings": []})

    monkeypatch.setattr(
        embedding_service,
        "_new_client",
        lambda: httpx.Client(
            base_url="http://ollama.test",
            transport=httpx.MockTransport(handler),
        ),
    )
    return requests


def vectors(count: int, *, dimensions: int = 768) -> list[list[float]]:
    return [
        [float(index == vector_index) for index in range(dimensions)]
        for vector_index in range(count)
    ]


def test_ollama_embeddings_use_configured_model_and_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = mocked_ollama(
        monkeypatch,
        response={"model": "embeddinggemma", "embeddings": vectors(2)},
    )

    result = embedding_service.generate_embeddings(["um", "dois"])

    assert len(result) == 2
    assert all(len(vector) == 768 for vector in result)
    assert requests == [
        {
            "model": embedding_service.config.OLLAMA_EMBEDDING_MODEL,
            "input": ["um", "dois"],
            "dimensions": 768,
        }
    ]


def test_ollama_connection_failure_is_wrapped_without_exception_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mocked_ollama(
        monkeypatch,
        failure=httpx.ConnectError("private connection detail"),
    )

    with pytest.raises(embedding_service.EmbeddingServiceError) as error:
        embedding_service.generate_embeddings(["consulta"])

    assert "private connection detail" not in str(error.value)


def test_document_embeddings_are_saved_per_chunk_with_model(
    embeddings_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, document_id, token = create_owned_document()
    mocked_ollama(
        monkeypatch,
        response={"model": "embeddinggemma", "embeddings": vectors(2)},
    )

    response = embeddings_client.post(
        f"/collections/{collection_id}/documents/{document_id}/embeddings",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "document_id": str(document_id),
        "embedding_model": "embeddinggemma",
        "chunk_count": 2,
    }
    with app.state.test_session_factory() as session:
        chunks = session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.position)
        ).all()
    assert [chunk.embedding_model for chunk in chunks] == [
        "embeddinggemma",
        "embeddinggemma",
    ]
    assert all(len(chunk.embedding) == 768 for chunk in chunks)


def test_reembedding_updates_vectors_and_model_for_existing_chunks(
    embeddings_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, document_id, token = create_owned_document()
    endpoint = (
        f"/collections/{collection_id}/documents/{document_id}/embeddings"
    )
    headers = {"Authorization": f"Bearer {token}"}
    mocked_ollama(
        monkeypatch,
        response={"model": "embeddinggemma", "embeddings": vectors(2)},
    )
    first = embeddings_client.post(endpoint, headers=headers)

    mocked_ollama(
        monkeypatch,
        response={
            "model": "embeddinggemma",
            "embeddings": [[0.5] * 768, [0.25] * 768],
        },
    )
    second = embeddings_client.post(endpoint, headers=headers)

    assert first.status_code == second.status_code == 200
    with app.state.test_session_factory() as session:
        chunks = session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.position)
        ).all()
    assert len(chunks) == 2
    assert [chunk.embedding_model for chunk in chunks] == [
        "embeddinggemma",
        "embeddinggemma",
    ]
    assert chunks[0].embedding == [0.5] * 768
    assert chunks[1].embedding == [0.25] * 768


def test_invalid_embedding_dimension_does_not_overwrite_stored_vectors(
    embeddings_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, document_id, token = create_owned_document()
    with app.state.test_session_factory() as session:
        chunks = session.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
        for chunk in chunks:
            chunk.embedding = vectors(1)[0]
            chunk.embedding_model = "previous-model"
        session.commit()
    mocked_ollama(
        monkeypatch,
        response={"model": "embeddinggemma", "embeddings": vectors(2, dimensions=7)},
    )

    response = embeddings_client.post(
        f"/collections/{collection_id}/documents/{document_id}/embeddings",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 502
    with app.state.test_session_factory() as session:
        chunks = session.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        ).all()
    assert [chunk.embedding_model for chunk in chunks] == [
        "previous-model",
        "previous-model",
    ]


def test_embedding_connection_failure_returns_safe_response(
    embeddings_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, document_id, token = create_owned_document()
    mocked_ollama(
        monkeypatch,
        failure=httpx.ConnectError("private connection detail"),
    )

    response = embeddings_client.post(
        f"/collections/{collection_id}/documents/{document_id}/embeddings",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 503
    assert "private connection detail" not in response.text


def test_embedding_generation_checks_collection_owner_before_ollama(
    embeddings_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, document_id, _ = create_owned_document()
    with app.state.test_session_factory() as session:
        stranger = User(email="stranger@example.test", password_hash="unused")
        session.add(stranger)
        session.commit()
        token = create_access_token(str(stranger.id))
    requests = mocked_ollama(
        monkeypatch,
        response={"model": "embeddinggemma", "embeddings": vectors(2)},
    )

    response = embeddings_client.post(
        f"/collections/{collection_id}/documents/{document_id}/embeddings",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert requests == []


def test_semantic_search_returns_matching_chunks_and_metadata(
    embeddings_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, document_id, token = create_owned_document()
    mocked_ollama(
        monkeypatch,
        response={"model": "embeddinggemma", "embeddings": vectors(1)},
    )

    def fake_search(*_args: Any, **_kwargs: Any) -> list[semantic_search.SearchHit]:
        return [
            semantic_search.SearchHit(
                chunk_id=UUID(int=1),
                document_id=document_id,
                document_name="manual.txt",
                page_number=None,
                position=0,
                content="Trecho relevante",
                score=0.91,
            )
        ]

    monkeypatch.setattr(embedding_routes, "search_chunks", fake_search)
    response = embeddings_client.post(
        f"/collections/{collection_id}/search",
        json={"query": "consulta", "limit": 3, "strategy": "vector"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "chunk_id": str(UUID(int=1)),
                "document_id": str(document_id),
                "document_name": "manual.txt",
                "page_number": None,
                "position": 0,
                "content": "Trecho relevante",
                "score": 0.91,
            }
        ]
    }


def test_search_checks_collection_owner_before_ollama(
    embeddings_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, _, _ = create_owned_document()
    with app.state.test_session_factory() as session:
        stranger = User(email="stranger@example.test", password_hash="unused")
        session.add(stranger)
        session.commit()
        token = create_access_token(str(stranger.id))
    requests = mocked_ollama(
        monkeypatch,
        response={"model": "embeddinggemma", "embeddings": vectors(1)},
    )

    response = embeddings_client.post(
        f"/collections/{collection_id}/search",
        json={"query": "segredo"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert requests == []


@pytest.mark.parametrize(
    "path,body",
    [
        (
            "/collections/00000000-0000-0000-0000-000000000001/search",
            {"query": "teste"},
        ),
        (
            "/collections/00000000-0000-0000-0000-000000000001/documents/"
            "00000000-0000-0000-0000-000000000002/embeddings",
            None,
        ),
    ],
)
def test_embedding_and_search_routes_require_authentication(
    embeddings_client: TestClient,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    response = (
        embeddings_client.post(path, json=body)
        if body is not None
        else embeddings_client.post(path)
    )

    assert response.status_code == 401


def test_similarity_query_uses_pgvector_cosine_distance() -> None:
    from sqlalchemy import select

    statement = semantic_search.build_search_statement(
        collection_id=UUID(int=1),
        embedding=[0.0] * 768,
        embedding_model="embeddinggemma",
        limit=5,
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "<=>" in sql


@pytest.mark.parametrize(
    ("strategy", "expected_search"),
    [
        ("text", "search_text_chunks"),
        ("vector", "search_chunks"),
        ("hybrid", "search_hybrid_chunks"),
    ],
)
def test_search_strategy_dispatch_and_text_does_not_call_ollama(
    embeddings_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    strategy: str,
    expected_search: str,
) -> None:
    _, collection_id, _, token = create_owned_document()
    calls: list[str] = []
    monkeypatch.setattr(
        embedding_routes,
        "_generate",
        lambda texts: calls.append("embedding") or [[0.0] * 768],
    )
    for name in ("search_text_chunks", "search_chunks", "search_hybrid_chunks"):
        monkeypatch.setattr(
            embedding_routes,
            name,
            lambda *args, _name=name, **kwargs: calls.append(_name) or [],
        )

    response = embeddings_client.post(
        f"/collections/{collection_id}/search",
        json={"query": "E-17 Orion B20", "strategy": strategy},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert calls[-1] == expected_search
    assert ("embedding" in calls) is (strategy != "text")


def test_search_defaults_to_hybrid(
    embeddings_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, collection_id, _, token = create_owned_document()
    calls: list[str] = []
    monkeypatch.setattr(embedding_routes, "_generate", lambda _: [[0.0] * 768])
    monkeypatch.setattr(
        embedding_routes,
        "search_hybrid_chunks",
        lambda *args, **kwargs: calls.append("hybrid") or [],
    )

    response = embeddings_client.post(
        f"/collections/{collection_id}/search",
        json={"query": "alimentação"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert calls == ["hybrid"]


@pytest.mark.parametrize("strategy", ["vector", "text", "hybrid"])
def test_other_user_cannot_search_any_strategy_before_retrieval(
    embeddings_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    strategy: str,
) -> None:
    _, collection_id, _, _ = create_owned_document("owner@example.test")
    with app.state.test_session_factory() as session:
        other = User(email="other@example.test", password_hash="unused")
        session.add(other)
        session.commit()
        other_token = create_access_token(str(other.id))

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("A busca ocorreu antes da validação de propriedade")

    monkeypatch.setattr(embedding_routes, "_generate", forbidden)
    monkeypatch.setattr(embedding_routes, "search_text_chunks", forbidden)
    monkeypatch.setattr(embedding_routes, "search_chunks", forbidden)
    monkeypatch.setattr(embedding_routes, "search_hybrid_chunks", forbidden)
    response = embeddings_client.post(
        f"/collections/{collection_id}/search",
        json={"query": "E-17", "strategy": strategy},
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 404

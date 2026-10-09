import json
from io import BytesIO
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy.dialects import postgresql
from uuid import UUID

from acervo_ia import config
from acervo_ia.services import gemini
from acervo_ia.services.chat import ChatModelError, generate_chat_completion
from acervo_ia.services.embeddings import (
    EmbeddingDimensionError,
    EmbeddingServiceError,
    generate_embeddings,
)
from acervo_ia.services.semantic_search import build_search_statement
from acervo_ia.services import storage


def _read_provider_settings(provider_environment: dict[str, str]) -> list[str]:
    project_root = Path(__file__).resolve().parents[1]
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(project_root / "src"),
    }
    environment.update(provider_environment)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from acervo_ia import config; print('|'.join(("
            "config.CHAT_PROVIDER, config.EMBEDDING_PROVIDER, "
            "config.DEMO_CHAT_PROVIDER, config.DEMO_EMBEDDING_PROVIDER)))",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result.stdout.strip().split("|")


def test_chat_and_embedding_providers_default_to_ollama() -> None:
    assert _read_provider_settings({}) == ["ollama"] * 4


def test_combined_legacy_provider_variables_remain_fallbacks() -> None:
    assert _read_provider_settings(
        {"AI_PROVIDER": "gemini", "DEMO_AI_PROVIDER": "gemini"}
    ) == ["gemini"] * 4


def test_independent_provider_settings_override_legacy_combined_values() -> None:
    assert _read_provider_settings(
        {
            "AI_PROVIDER": "gemini",
            "DEMO_AI_PROVIDER": "gemini",
            "CHAT_PROVIDER": "ollama",
            "EMBEDDING_PROVIDER": "gemini",
            "DEMO_CHAT_PROVIDER": "gemini",
            "DEMO_EMBEDDING_PROVIDER": "ollama",
        }
    ) == ["ollama", "gemini", "gemini", "ollama"]


def _client(monkeypatch, handler):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "sentinel-gemini-key")
    original_client = httpx.Client

    def mocked_client(**kwargs):
        return original_client(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(gemini.httpx, "Client", mocked_client)


def test_gemini_embedding_requests_configured_768_dimensions_without_key_in_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = "sentinel-gemini-key"
    observed = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        payload = json.loads(request.content)
        assert payload["requests"][0]["outputDimensionality"] == 768
        return httpx.Response(200, json={"embeddings": [{"values": [0.1] * 768}]})

    _client(monkeypatch, handler)
    vectors = generate_embeddings(["fictitious chunk"], provider="gemini")
    assert len(vectors[0]) == 768
    assert observed[0].headers["x-goog-api-key"] == key
    assert key not in str(observed[0].url)
    assert observed[0].url.path.endswith("gemini-embedding-2:batchEmbedContents")


def test_gemini_embedding_rejects_dimensions_that_do_not_fit_pgvector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "GEMINI_API_KEY", "sentinel-key")
    _client(
        monkeypatch,
        lambda _request: httpx.Response(200, json={"embeddings": [{"values": [0.1] * 7}]}),
    )
    with pytest.raises(EmbeddingDimensionError):
        generate_embeddings(["fictitious"], provider="gemini")


def test_gemini_generation_sends_system_instruction_and_json_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "GEMINI_API_KEY", "sentinel-key")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "systemInstruction" in payload
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert payload["generationConfig"]["maxOutputTokens"] == 111
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": '{"answer":"ok","citations":[]}'}]}}]},
        )

    _client(monkeypatch, handler)
    result = gemini.complete(
        [{"role": "system", "content": "system sentinel"}, {"role": "user", "content": "question sentinel"}],
        "gemini-3.1-flash-lite",
        max_output_tokens=111,
    )
    assert json.loads(result)["answer"] == "ok"


def test_missing_key_and_provider_http_429_are_safe_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(EmbeddingServiceError) as missing:
        generate_embeddings(["fictional"], provider="gemini")
    assert "key" not in str(missing.value).lower()

    _client(
        monkeypatch,
        lambda _request: httpx.Response(429, text="provider-secret-response"),
    )
    with pytest.raises(ChatModelError) as rate_limited:
        generate_chat_completion([{"role": "user", "content": "question sentinel"}], provider="gemini")
    assert "provider-secret-response" not in str(rate_limited.value)


def test_search_statement_filters_provider_and_model_pair() -> None:
    statement = build_search_statement(
        collection_id=UUID(int=1),
        embedding=[0.0] * 768,
        embedding_model="gemini-embedding-2",
        limit=5,
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "document_chunks.embedding_model =" in sql
    assert "document_chunks.embedding_provider =" in sql


def test_private_s3_storage_uses_internal_keys_and_safe_provider_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self):
            self.objects = {}

        def put_object(self, **kwargs):
            assert kwargs["ServerSideEncryption"] == "AES256"
            self.objects[kwargs["Key"]] = kwargs["Body"]

        def get_object(self, **kwargs):
            return {"Body": BytesIO(self.objects[kwargs["Key"]])}

        def delete_object(self, **kwargs):
            self.objects.pop(kwargs["Key"], None)

    client = FakeClient()
    monkeypatch.setattr(config, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(config, "S3_BUCKET", "private-bucket")
    monkeypatch.setattr(storage, "_s3_client", lambda: client)
    key = "a" * 32
    storage.store(key, b"fictional document")
    assert storage.open_file(key).read() == b"fictional document"
    storage.delete(key)
    assert key not in client.objects

    with pytest.raises(storage.StorageUnavailable):
        storage.store("../unsafe", b"x")

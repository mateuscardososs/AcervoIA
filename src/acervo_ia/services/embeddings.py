import math
from typing import Any

import httpx

from acervo_ia import config


class EmbeddingServiceError(RuntimeError):
    """Safe-to-handle local embedding service error without provider details."""


class EmbeddingDimensionError(EmbeddingServiceError):
    """The provider returned data incompatible with the pgvector column."""


def _new_client() -> httpx.Client:
    return httpx.Client(
        base_url=config.OLLAMA_BASE_URL,
        timeout=config.OLLAMA_TIMEOUT_SECONDS,
    )


def generate_embeddings(
    texts: list[str],
    *,
    model: str | None = None,
) -> list[list[float]]:
    if not texts:
        return []

    selected_model = model or config.OLLAMA_EMBEDDING_MODEL
    try:
        with _new_client() as client:
            response = client.post(
                "/api/embed",
                json={
                    "model": selected_model,
                    "input": texts,
                    "dimensions": config.EMBEDDING_DIMENSIONS,
                },
            )
            response.raise_for_status()
            payload: Any = response.json()
    except (httpx.HTTPError, ValueError):
        raise EmbeddingServiceError(
            "O serviço local de embeddings está indisponível."
        ) from None

    vectors = payload.get("embeddings") if isinstance(payload, dict) else None
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise EmbeddingServiceError(
            "O serviço local de embeddings retornou uma resposta inválida."
        )

    validated: list[list[float]] = []
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != config.EMBEDDING_DIMENSIONS:
            raise EmbeddingDimensionError(
                "A dimensão retornada não corresponde à coluna vetorial."
            )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in vector
        ):
            raise EmbeddingServiceError(
                "O serviço local de embeddings retornou uma resposta inválida."
            )
        validated.append([float(value) for value in vector])
    return validated

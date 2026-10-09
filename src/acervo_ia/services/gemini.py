"""Minimal Gemini Developer API adapter. Credentials stay in server headers."""

from typing import Any

import httpx

from acervo_ia import config


class GeminiUnavailable(RuntimeError):
    """Provider failure with no request, prompt, or credential details."""


def _new_client() -> httpx.Client:
    if not config.GEMINI_API_KEY:
        raise GeminiUnavailable
    return httpx.Client(
        base_url=config.GEMINI_API_BASE_URL,
        headers={"x-goog-api-key": config.GEMINI_API_KEY},
        timeout=max(config.OLLAMA_TIMEOUT_SECONDS, config.OLLAMA_CHAT_TIMEOUT_SECONDS),
    )


def embed(texts: list[str], model: str, before_call: Any = None) -> list[list[float]]:
    if before_call is not None:
        before_call()
    requests = [
        {
            "model": f"models/{model}",
            "content": {"parts": [{"text": content}]},
            "outputDimensionality": config.EMBEDDING_DIMENSIONS,
        }
        for content in texts
    ]
    try:
        with _new_client() as client:
            response = client.post(f"/models/{model}:batchEmbedContents", json={"requests": requests})
            response.raise_for_status()
            payload: Any = response.json()
    except (httpx.HTTPError, ValueError, GeminiUnavailable):
        raise GeminiUnavailable from None
    items = payload.get("embeddings") if isinstance(payload, dict) else None
    if not isinstance(items, list) or len(items) != len(texts):
        raise GeminiUnavailable
    vectors = [item.get("values") if isinstance(item, dict) else None for item in items]
    if any(not isinstance(vector, list) for vector in vectors):
        raise GeminiUnavailable
    return vectors


def complete(
    messages: list[dict[str, str]], model: str, *, max_output_tokens: int,
    before_call: Any = None,
) -> str:
    if before_call is not None:
        before_call()
    system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
    contents = [
        {
            "role": "model" if message.get("role") == "assistant" else "user",
            "parts": [{"text": message.get("content", "")}],
        }
        for message in messages
        if message.get("role") != "system"
    ]
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": max_output_tokens,
        },
    }
    try:
        with _new_client() as client:
            response = client.post(f"/models/{model}:generateContent", json=body)
            response.raise_for_status()
            payload: Any = response.json()
    except (httpx.HTTPError, ValueError, GeminiUnavailable):
        raise GeminiUnavailable from None
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    candidate = candidates[0] if isinstance(candidates, list) and candidates else None
    content = candidate.get("content") if isinstance(candidate, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    texts = [part.get("text") for part in parts or [] if isinstance(part, dict)]
    if not texts or any(not isinstance(item, str) for item in texts):
        raise GeminiUnavailable
    return "".join(texts)

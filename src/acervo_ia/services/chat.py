from typing import Any

import httpx

from acervo_ia import config


class ChatModelError(RuntimeError):
    """Safe chat provider failure that excludes transport details."""


def _new_client() -> httpx.Client:
    return httpx.Client(
        base_url=config.OLLAMA_BASE_URL,
        timeout=config.OLLAMA_CHAT_TIMEOUT_SECONDS,
    )


def generate_chat_completion(messages: list[dict[str, str]]) -> str:
    try:
        with _new_client() as client:
            response = client.post(
                "/api/chat",
                json={
                    "model": config.OLLAMA_CHAT_MODEL,
                    "messages": messages,
                    "format": "json",
                    "stream": False,
                },
            )
            response.raise_for_status()
            payload: Any = response.json()
    except (httpx.HTTPError, ValueError):
        raise ChatModelError("O modelo local não está disponível.") from None

    message = payload.get("message") if isinstance(payload, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ChatModelError("O modelo local retornou uma resposta inválida.")
    return content

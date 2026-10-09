from typing import Any
from collections.abc import Callable

import httpx

from acervo_ia import config
from acervo_ia.services import gemini


class ChatModelError(RuntimeError):
    """Safe chat provider failure that excludes transport details."""


def _new_client() -> httpx.Client:
    return httpx.Client(
        base_url=config.OLLAMA_BASE_URL,
        timeout=config.OLLAMA_CHAT_TIMEOUT_SECONDS,
    )


def generate_chat_completion(
    messages: list[dict[str, str]],
    *,
    provider: str | None = None,
    before_call: Callable[[], None] | None = None,
) -> str:
    selected_provider = provider or config.CHAT_PROVIDER
    if selected_provider == "gemini":
        try:
            return gemini.complete(
                messages,
                config.GEMINI_CHAT_MODEL,
                max_output_tokens=config.DEMO_MAX_OUTPUT_TOKENS,
                before_call=before_call,
            )
        except gemini.GeminiUnavailable:
            raise ChatModelError("O provedor de respostas está indisponível.") from None
    if selected_provider != "ollama":
        raise ChatModelError("O provedor de respostas não está configurado.")
    try:
        with _new_client() as client:
            response = client.post(
                "/api/chat",
                json={
                    "model": config.OLLAMA_CHAT_MODEL,
                    "messages": messages,
                    "format": "json",
                    "stream": False,
                    "options": {"num_predict": config.DEMO_MAX_OUTPUT_TOKENS},
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

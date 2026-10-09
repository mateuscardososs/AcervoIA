import os
from pathlib import Path

DOCUMENT_FORMATS = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".txt": "text/plain",
}
MAX_DOCUMENT_SIZE_BYTES = 20 * 1024 * 1024
CHUNK_SIZE_CHARS = 1_000
CHUNK_OVERLAP_CHARS = 150
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "embeddinggemma")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "qwen2.5:3b")
EMBEDDING_DIMENSIONS = 768
OLLAMA_TIMEOUT_SECONDS = 60.0
OLLAMA_CHAT_TIMEOUT_SECONDS = 120.0
DOCUMENT_STORAGE_DIRECTORY = Path(__file__).resolve().parents[2] / "data" / "uploads"


def _provider_setting(name: str, legacy_name: str | None = None) -> str:
    value = os.getenv(name)
    if not value and legacy_name:
        value = os.getenv(legacy_name)
    return (value or "ollama").strip().lower()


# Keep the combined settings as compatibility aliases for existing .env files.
AI_PROVIDER = _provider_setting("AI_PROVIDER")
DEMO_AI_PROVIDER = _provider_setting("DEMO_AI_PROVIDER")
CHAT_PROVIDER = _provider_setting("CHAT_PROVIDER", "AI_PROVIDER")
EMBEDDING_PROVIDER = _provider_setting("EMBEDDING_PROVIDER", "AI_PROVIDER")
DEMO_CHAT_PROVIDER = _provider_setting("DEMO_CHAT_PROVIDER", "DEMO_AI_PROVIDER")
DEMO_EMBEDDING_PROVIDER = _provider_setting(
    "DEMO_EMBEDDING_PROVIDER", "DEMO_AI_PROVIDER"
)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_BASE_URL = os.getenv(
    "GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
)
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.1-flash-lite")
DEMO_ACCOUNT_EMAIL = os.getenv("DEMO_ACCOUNT_EMAIL", "public-demo@example.invalid")
DEMO_COLLECTION_NAME = "[DEMO PÚBLICA] Manuais fictícios"
DEMO_ENABLED = os.getenv("DEMO_ENABLED", "false").strip().lower() == "true"
GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "false").strip().lower() == "true"
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
CORS_ALLOWED_ORIGINS = tuple(
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://127.0.0.1:5173").split(",")
    if origin.strip()
)
DEMO_LOGIN_LIMIT_PER_IP = int(os.getenv("DEMO_LOGIN_LIMIT_PER_IP", "10"))
DEMO_QUESTION_LIMIT_PER_IP = int(os.getenv("DEMO_QUESTION_LIMIT_PER_IP", "5"))
DEMO_QUESTION_WINDOW_SECONDS = int(os.getenv("DEMO_QUESTION_WINDOW_SECONDS", "3600"))
GEMINI_DAILY_CALL_LIMIT = int(os.getenv("GEMINI_DAILY_CALL_LIMIT", "100"))
DEMO_MAX_QUESTION_CHARS = int(os.getenv("DEMO_MAX_QUESTION_CHARS", "2000"))
DEMO_MAX_CONTEXT_CHARS = int(os.getenv("DEMO_MAX_CONTEXT_CHARS", "12000"))
DEMO_MAX_OUTPUT_TOKENS = int(os.getenv("DEMO_MAX_OUTPUT_TOKENS", "700"))
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL") or None
S3_REGION = os.getenv("S3_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID") or None
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY") or None

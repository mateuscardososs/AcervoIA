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
EMBEDDING_DIMENSIONS = 768
OLLAMA_TIMEOUT_SECONDS = 60.0
DOCUMENT_STORAGE_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "data" / "uploads"
)

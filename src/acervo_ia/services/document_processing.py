from dataclasses import dataclass
from pathlib import Path

from docx import Document as WordDocument
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from acervo_ia import config


class DocumentExtractionError(RuntimeError):
    """A safe, user-facing document extraction failure."""


@dataclass(frozen=True)
class TextPage:
    text: str
    page_number: int | None


@dataclass(frozen=True)
class TextChunk:
    content: str
    page_number: int | None


def extract_document_pages(path: Path, content_type: str) -> list[TextPage]:
    try:
        if content_type == "text/plain":
            return [TextPage(path.read_bytes().decode("utf-8-sig"), None)]

        if content_type == "application/pdf":
            reader = PdfReader(path, strict=False)
            return [
                TextPage(page.extract_text() or "", page_number)
                for page_number, page in enumerate(reader.pages, start=1)
            ]

        if (
            content_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            document = WordDocument(path)
            blocks: list[str] = []
            for item in document.iter_inner_content():
                if isinstance(item, Paragraph):
                    blocks.append(item.text)
                elif isinstance(item, Table):
                    blocks.extend(
                        "\t".join(cell.text for cell in row.cells)
                        for row in item.rows
                    )
            return [TextPage("\n".join(blocks), None)]
    except Exception:
        raise DocumentExtractionError from None

    raise DocumentExtractionError


def chunk_pages(
    pages: list[TextPage],
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[TextChunk]:
    size = config.CHUNK_SIZE_CHARS if chunk_size is None else chunk_size
    chunk_overlap = config.CHUNK_OVERLAP_CHARS if overlap is None else overlap
    if size <= 0 or chunk_overlap < 0 or chunk_overlap >= size:
        raise ValueError("Chunk size and overlap configuration are invalid.")

    step = size - chunk_overlap
    chunks: list[TextChunk] = []
    for page in pages:
        if not page.text.strip():
            continue
        start = 0
        while start < len(page.text):
            end = min(start + size, len(page.text))
            content = page.text[start:end]
            if content.strip():
                chunks.append(TextChunk(content=content, page_number=page.page_number))
            if end == len(page.text):
                break
            start += step
    return chunks

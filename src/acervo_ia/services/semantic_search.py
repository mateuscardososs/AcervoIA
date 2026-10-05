from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from acervo_ia.db.models import Document, DocumentChunk


@dataclass(frozen=True)
class SearchHit:
    chunk_id: UUID
    document_id: UUID
    document_name: str
    page_number: int | None
    position: int
    content: str
    score: float


def build_search_statement(
    *,
    collection_id: UUID,
    embedding: list[float],
    embedding_model: str,
    limit: int,
) -> Select[tuple[DocumentChunk, Document, float]]:
    distance = DocumentChunk.embedding.cosine_distance(embedding).label("distance")
    return (
        select(DocumentChunk, Document, distance)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.collection_id == collection_id,
            DocumentChunk.embedding.is_not(None),
            DocumentChunk.embedding_model == embedding_model,
        )
        .order_by(distance)
        .limit(limit)
    )


def search_chunks(
    session: Session,
    *,
    collection_id: UUID,
    embedding: list[float],
    embedding_model: str,
    limit: int,
) -> list[SearchHit]:
    rows = session.execute(
        build_search_statement(
            collection_id=collection_id,
            embedding=embedding,
            embedding_model=embedding_model,
            limit=limit,
        )
    ).all()
    return [
        SearchHit(
            chunk_id=chunk.id,
            document_id=document.id,
            document_name=document.original_filename,
            page_number=chunk.page_number,
            position=chunk.position,
            content=chunk.content,
            score=1.0 - distance,
        )
        for chunk, document, distance in rows
    ]

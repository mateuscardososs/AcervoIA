from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from acervo_ia import config
from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Collection, Document, DocumentChunk, User
from acervo_ia.security import get_current_user
from acervo_ia.services.embeddings import (
    EmbeddingDimensionError,
    EmbeddingServiceError,
    generate_embeddings,
)
from acervo_ia.services.semantic_search import SearchHit, search_chunks

router = APIRouter(prefix="/collections", tags=["semantic search"])


class DocumentEmbeddingResponse(BaseModel):
    document_id: UUID
    embedding_model: str
    chunk_count: int


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4_000)
    limit: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_name: str
    page_number: int | None
    position: int
    content: str
    score: float


class SemanticSearchResponse(BaseModel):
    results: list[SearchResult]


def _get_owned_collection(
    collection_id: UUID,
    user: User,
    session: Session,
) -> Collection:
    collection = session.scalar(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.owner_id == user.id,
        )
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Coleção não encontrada.")
    return collection


def _generate(texts: list[str]) -> list[list[float]]:
    try:
        return generate_embeddings(texts, model=config.OLLAMA_EMBEDDING_MODEL)
    except EmbeddingDimensionError:
        raise HTTPException(
            status_code=502,
            detail="O modelo local retornou vetores incompatíveis com a busca.",
        ) from None
    except EmbeddingServiceError:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível usar o serviço local de embeddings.",
        ) from None


@router.post(
    "/{collection_id}/documents/{document_id}/embeddings",
    response_model=DocumentEmbeddingResponse,
)
def embed_document(
    collection_id: UUID,
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> DocumentEmbeddingResponse:
    collection = _get_owned_collection(collection_id, user, session)
    document = session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.collection_id == collection.id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")

    chunks = session.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.position)
    ).all()
    if document.processing_status != "completed" or not chunks:
        raise HTTPException(
            status_code=409,
            detail="O documento ainda não possui trechos processados.",
        )

    vectors = _generate([chunk.content for chunk in chunks])
    if len(vectors) != len(chunks):
        raise HTTPException(
            status_code=502,
            detail="O modelo local retornou uma resposta incompatível com o documento.",
        )

    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
        chunk.embedding_model = config.OLLAMA_EMBEDDING_MODEL
    session.commit()
    return DocumentEmbeddingResponse(
        document_id=document.id,
        embedding_model=config.OLLAMA_EMBEDDING_MODEL,
        chunk_count=len(chunks),
    )


@router.post(
    "/{collection_id}/search",
    response_model=SemanticSearchResponse,
)
def search_collection(
    collection_id: UUID,
    request: SemanticSearchRequest,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> SemanticSearchResponse:
    # Check tenant ownership before calling Ollama or querying vector results.
    _get_owned_collection(collection_id, user, session)
    query_vector = _generate([request.query])[0]
    hits: list[SearchHit] = search_chunks(
        session,
        collection_id=collection_id,
        embedding=query_vector,
        embedding_model=config.OLLAMA_EMBEDDING_MODEL,
        limit=request.limit,
    )
    return SemanticSearchResponse(
        results=[SearchResult.model_validate(hit.__dict__) for hit in hits]
    )

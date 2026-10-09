from collections.abc import Callable
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from acervo_ia import config
from acervo_ia.api.document_scope import validate_document_filter
from acervo_ia.api.demo_access import ensure_writable_user
from acervo_ia.api.document_task_schemas import DocumentTaskResponse
from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Collection, Document, DocumentChunk, User
from acervo_ia.security import get_current_user
from acervo_ia.services.document_tasks import (
    ActiveDocumentTaskError,
    DocumentTaskQueueError,
    enqueue_document_task,
)
from acervo_ia.services.embeddings import (
    EmbeddingDimensionError,
    EmbeddingServiceError,
    generate_embeddings,
)
from acervo_ia.services.semantic_search import (
    SearchHit,
    search_chunks,
    search_hybrid_chunks,
    search_text_chunks,
)
from acervo_ia.services.usage_limits import (
    reserve_demo_question,
    reserve_gemini_call,
    require_public_demo_enabled,
)

router = APIRouter(prefix="/collections", tags=["semantic search"])


class SemanticSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4_000)
    limit: int = Field(default=5, ge=1, le=20)
    strategy: Literal["vector", "text", "hybrid"] = "hybrid"
    document_ids: list[UUID] = Field(default_factory=list)


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


def _generate(
    texts: list[str],
    *,
    provider: str | None = None,
    before_call: Callable[[], None] | None = None,
) -> list[list[float]]:
    try:
        selected_provider = provider or config.EMBEDDING_PROVIDER
        model = (
            config.GEMINI_EMBEDDING_MODEL
            if selected_provider == "gemini"
            else config.OLLAMA_EMBEDDING_MODEL
        )
        return generate_embeddings(
            texts, model=model, provider=selected_provider, before_call=before_call
        )
    except EmbeddingDimensionError:
        raise HTTPException(
            status_code=502,
            detail="O provedor retornou vetores incompatíveis com a busca.",
        ) from None
    except EmbeddingServiceError:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível usar o serviço de embeddings.",
        ) from None


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


@router.post(
    "/{collection_id}/documents/{document_id}/embeddings",
    response_model=DocumentTaskResponse,
    status_code=202,
)
def embed_document(
    collection_id: UUID,
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> DocumentTaskResponse:
    ensure_writable_user(user)
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

    try:
        task = enqueue_document_task(
            session,
            document=document,
            collection=collection,
            user=user,
            task_type="embeddings",
        )
    except ActiveDocumentTaskError:
        raise HTTPException(
            status_code=409,
            detail="Já existe outra tarefa ativa para este documento.",
        ) from None
    except DocumentTaskQueueError:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível iniciar a geração de vetores.",
        ) from None
    return DocumentTaskResponse.model_validate(task)


@router.post(
    "/{collection_id}/search",
    response_model=SemanticSearchResponse,
)
def search_collection(
    collection_id: UUID,
    request: SemanticSearchRequest,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    request_context: Request,
) -> SemanticSearchResponse:
    # Check tenant ownership before calling Ollama or querying vector results.
    collection = _get_owned_collection(collection_id, user, session)
    document_ids = validate_document_filter(
        session,
        collection_id=collection.id,
        document_ids=request.document_ids,
    )
    if user.is_demo:
        require_public_demo_enabled(session)
        if len(request.query) > config.DEMO_MAX_QUESTION_CHARS:
            raise HTTPException(status_code=422, detail="A consulta excede o limite da demonstração.")
        reserve_demo_question(session, request_context)
    selected_provider = (
        config.DEMO_EMBEDDING_PROVIDER if user.is_demo else config.EMBEDDING_PROVIDER
    )
    before_call = (lambda: reserve_gemini_call(session)) if selected_provider == "gemini" else None
    if request.strategy == "text":
        hits: list[SearchHit] = search_text_chunks(
            session,
            collection_id=collection_id,
            query=request.query,
            limit=request.limit,
            document_ids=document_ids,
        )
    else:
        query_vectors = (
            _generate([request.query], provider=selected_provider, before_call=before_call)
            if before_call is not None or selected_provider != config.EMBEDDING_PROVIDER
            else _generate([request.query])
        )
        query_vector = query_vectors[0]
        if request.strategy == "vector":
            hits = search_chunks(
                session,
                collection_id=collection_id,
                embedding=query_vector,
                embedding_model=(config.GEMINI_EMBEDDING_MODEL if selected_provider == "gemini" else config.OLLAMA_EMBEDDING_MODEL),
                embedding_provider=selected_provider,
                limit=request.limit,
                document_ids=document_ids,
            )
        else:
            hits = search_hybrid_chunks(
                session,
                collection_id=collection_id,
                query=request.query,
                embedding=query_vector,
                embedding_model=(config.GEMINI_EMBEDDING_MODEL if selected_provider == "gemini" else config.OLLAMA_EMBEDDING_MODEL),
                embedding_provider=selected_provider,
                limit=request.limit,
                document_ids=document_ids,
            )
    if document_ids:
        allowed_document_ids = set(document_ids)
        hits = [hit for hit in hits if hit.document_id in allowed_document_ids]
    return SemanticSearchResponse(
        results=[SearchResult.model_validate(hit.__dict__) for hit in hits]
    )

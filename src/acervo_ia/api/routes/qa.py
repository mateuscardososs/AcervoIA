from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from acervo_ia.api.document_scope import validate_document_filter
from acervo_ia import config
from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Collection, QuestionHistory, User
from acervo_ia.security import get_current_user
from acervo_ia.services import question_answering
from acervo_ia.services.chat import ChatModelError
from acervo_ia.services.embeddings import (
    EmbeddingDimensionError,
    EmbeddingServiceError,
)
from acervo_ia.services.usage_limits import reserve_demo_question, reserve_gemini_call, require_public_demo_enabled

router = APIRouter(prefix="/collections", tags=["questions and answers"])

INVALID_MODEL_ANSWER = "O modelo local retornou uma resposta que não pôde ser validada."


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)
    limit: int = Field(default=5, ge=1, le=10)
    strategy: Literal["vector", "text", "hybrid"] = "vector"
    document_ids: list[UUID] = Field(default_factory=list)


class AskSource(BaseModel):
    source_id: str
    document_id: UUID
    document_name: str
    page_number: int | None
    snippet: str


class AskResponse(BaseModel):
    answer: str
    sources: list[AskSource]


class AskHistoryItem(BaseModel):
    id: UUID
    question: str
    strategy: Literal["vector", "text", "hybrid"]
    document_ids: list[UUID]
    answer: str
    sources: list[AskSource]
    created_at: datetime


class AskHistoryPage(BaseModel):
    items: list[AskHistoryItem]
    limit: int
    offset: int
    has_more: bool


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


@router.post("/{collection_id}/ask", response_model=AskResponse)
def ask_collection(
    collection_id: UUID,
    request: AskRequest,
    http_request: Request,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AskResponse:
    # Enforce tenant ownership before embedding, searching, or using the chat model.
    collection = _get_owned_collection(collection_id, user, session)
    if user.is_demo:
        require_public_demo_enabled(session)
        if len(request.question) > config.DEMO_MAX_QUESTION_CHARS:
            raise HTTPException(status_code=422, detail="A pergunta excede o limite da demonstração.")
        reserve_demo_question(session, http_request)
    document_ids = validate_document_filter(
        session,
        collection_id=collection.id,
        document_ids=request.document_ids,
    )
    chat_provider = config.DEMO_CHAT_PROVIDER if user.is_demo else config.CHAT_PROVIDER
    embedding_provider = (
        config.DEMO_EMBEDDING_PROVIDER if user.is_demo else config.EMBEDDING_PROVIDER
    )
    try:
        answer_options = {
            "chat_provider": chat_provider,
            "embedding_provider": embedding_provider,
        }
        if chat_provider == "gemini":
            answer_options["before_chat_call"] = lambda: reserve_gemini_call(session)
        if embedding_provider == "gemini":
            answer_options["before_embedding_call"] = lambda: reserve_gemini_call(session)
        answer = question_answering.answer_question(
            session,
            collection_id=collection.id,
            question=request.question,
            limit=min(request.limit, 5) if user.is_demo else request.limit,
            strategy=request.strategy,
            document_ids=document_ids,
            max_context_chars=(config.DEMO_MAX_CONTEXT_CHARS if user.is_demo else None),
            **answer_options,
        )
    except EmbeddingDimensionError:
        raise HTTPException(
            status_code=502,
            detail="O provedor de embeddings retornou vetores incompatíveis com a busca.",
        ) from None
    except EmbeddingServiceError:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível usar o serviço de embeddings.",
        ) from None
    except ChatModelError:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível gerar uma resposta com o provedor configurado.",
        ) from None
    except question_answering.InvalidModelAnswer:
        raise HTTPException(status_code=502, detail=INVALID_MODEL_ANSWER) from None
    response = AskResponse(
        answer=answer.answer,
        sources=[AskSource(**source.__dict__) for source in answer.sources],
    )
    if not answer.correction_failed and not user.is_demo:
        history_entry = QuestionHistory(
            collection_id=collection.id,
            question=request.question,
            strategy=request.strategy,
            document_ids=[str(document_id) for document_id in document_ids or []],
            answer=response.answer,
            sources=[source.model_dump(mode="json") for source in response.sources],
        )
        session.add(history_entry)
        try:
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            raise HTTPException(
                status_code=503,
                detail="Não foi possível salvar a resposta no histórico.",
            ) from None
    return response


@router.get(
    "/{collection_id}/history",
    response_model=AskHistoryPage,
)
def list_collection_history(
    collection_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> AskHistoryPage:
    collection = _get_owned_collection(collection_id, user, session)
    if user.is_demo:
        return AskHistoryPage(items=[], limit=limit, offset=offset, has_more=False)
    entries = session.scalars(
        select(QuestionHistory)
        .where(QuestionHistory.collection_id == collection.id)
        .order_by(
            desc(QuestionHistory.created_at),
            desc(QuestionHistory.id),
        )
        .offset(offset)
        .limit(limit + 1)
    ).all()
    has_more = len(entries) > limit
    items = [
        AskHistoryItem(
            id=entry.id,
            question=entry.question,
            strategy=entry.strategy,
            document_ids=[UUID(document_id) for document_id in entry.document_ids],
            answer=entry.answer,
            sources=[AskSource(**source) for source in entry.sources],
            created_at=entry.created_at,
        )
        for entry in entries[:limit]
    ]
    return AskHistoryPage(
        items=items,
        limit=limit,
        offset=offset,
        has_more=has_more,
    )

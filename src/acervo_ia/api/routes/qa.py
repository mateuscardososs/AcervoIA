from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Collection, QuestionHistory, User
from acervo_ia.security import get_current_user
from acervo_ia.services import question_answering
from acervo_ia.services.chat import ChatModelError
from acervo_ia.services.embeddings import (
    EmbeddingDimensionError,
    EmbeddingServiceError,
)

router = APIRouter(prefix="/collections", tags=["questions and answers"])

INVALID_MODEL_ANSWER = "O modelo local retornou uma resposta que não pôde ser validada."


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)
    limit: int = Field(default=5, ge=1, le=10)
    strategy: Literal["vector", "text", "hybrid"] = "vector"


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
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> AskResponse:
    # Enforce tenant ownership before embedding, searching, or using the chat model.
    collection = _get_owned_collection(collection_id, user, session)
    try:
        answer = question_answering.answer_question(
            session,
            collection_id=collection.id,
            question=request.question,
            limit=request.limit,
            strategy=request.strategy,
        )
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
    except ChatModelError:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível gerar uma resposta com o modelo local.",
        ) from None
    except question_answering.InvalidModelAnswer:
        raise HTTPException(status_code=502, detail=INVALID_MODEL_ANSWER) from None
    response = AskResponse(
        answer=answer.answer,
        sources=[AskSource(**source.__dict__) for source in answer.sources],
    )
    if not answer.correction_failed:
        history_entry = QuestionHistory(
            collection_id=collection.id,
            question=request.question,
            strategy=request.strategy,
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

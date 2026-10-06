from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Collection, User
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
    return AskResponse(
        answer=answer.answer,
        sources=[AskSource(**source.__dict__) for source in answer.sources],
    )

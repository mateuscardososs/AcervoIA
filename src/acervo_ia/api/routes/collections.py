from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from acervo_ia.db.connection import get_db
from acervo_ia.api.demo_access import ensure_writable_user
from acervo_ia.db.models import Collection, User
from acervo_ia.security import get_current_user

router = APIRouter(prefix="/collections", tags=["collections"])


class CollectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=120)
    description: str | None = None


class CollectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    description: str | None = None


class CollectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    created_at: datetime


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Coleção não encontrada.",
        )
    return collection


def _duplicate_name_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Já existe uma coleção com este nome.",
    )


def _is_duplicate_name_error(error: IntegrityError) -> bool:
    diagnostic = getattr(error.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == "uq_collections_owner_name":
        return True
    return str(error.orig) == (
        "UNIQUE constraint failed: collections.owner_id, collections.name"
    )


@router.post(
    "",
    response_model=CollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_collection(
    payload: CollectionCreate,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> CollectionResponse:
    ensure_writable_user(user)
    collection = Collection(
        owner_id=user.id,
        name=payload.name,
        description=payload.description,
    )
    session.add(collection)
    try:
        session.commit()
    except IntegrityError as error:
        if _is_duplicate_name_error(error):
            raise _duplicate_name_error() from None
        raise
    session.refresh(collection)
    return CollectionResponse.model_validate(collection)


@router.get("", response_model=list[CollectionResponse])
def list_collections(
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[CollectionResponse]:
    collections = session.scalars(
        select(Collection)
        .where(Collection.owner_id == user.id)
        .order_by(Collection.created_at, Collection.id)
    ).all()
    return [CollectionResponse.model_validate(item) for item in collections]


@router.get("/{collection_id}", response_model=CollectionResponse)
def get_collection(
    collection_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> CollectionResponse:
    collection = _get_owned_collection(collection_id, user, session)
    return CollectionResponse.model_validate(collection)


@router.patch("/{collection_id}", response_model=CollectionResponse)
def update_collection(
    collection_id: UUID,
    payload: CollectionUpdate,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> CollectionResponse:
    ensure_writable_user(user)
    collection = _get_owned_collection(collection_id, user, session)
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O nome da coleção não pode ser nulo.",
        )
    for field, value in changes.items():
        setattr(collection, field, value)

    try:
        session.commit()
    except IntegrityError as error:
        if _is_duplicate_name_error(error):
            raise _duplicate_name_error() from None
        raise
    session.refresh(collection)
    return CollectionResponse.model_validate(collection)


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection(
    collection_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    ensure_writable_user(user)
    collection = _get_owned_collection(collection_id, user, session)
    session.delete(collection)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from acervo_ia.config import (
    DOCUMENT_FORMATS,
    DOCUMENT_STORAGE_DIRECTORY,
    MAX_DOCUMENT_SIZE_BYTES,
)
from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Collection, Document, User
from acervo_ia.security import get_current_user

router = APIRouter(prefix="/collections", tags=["documents"])


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
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


def _is_supported_content(extension: str, content: bytes) -> bool:
    if extension == ".txt":
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return False
        return b"\x00" not in content
    if extension == ".pdf":
        return content.startswith(b"%PDF-")
    if extension == ".docx":
        try:
            with ZipFile(BytesIO(content)) as archive:
                names = set(archive.namelist())
        except (BadZipFile, OSError):
            return False
        return {"[Content_Types].xml", "word/document.xml"}.issubset(names)
    return False


def _safe_storage_path(storage_key: str) -> Path:
    if len(storage_key) != 32 or any(
        character not in "0123456789abcdef" for character in storage_key
    ):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível acessar o arquivo armazenado.",
        )
    return DOCUMENT_STORAGE_DIRECTORY / storage_key


def _store_content(storage_key: str, content: bytes) -> Path:
    path = _safe_storage_path(storage_key)
    created = False
    try:
        DOCUMENT_STORAGE_DIRECTORY.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as stored_file:
            stored_file.write(content)
    except OSError:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível armazenar o arquivo.",
        ) from None
    return path


@router.post(
    "/{collection_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    collection_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
) -> DocumentResponse:
    collection = _get_owned_collection(collection_id, user, session)
    filename = file.filename
    if not filename:
        file.file.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo não é válido ou não é aceito.",
        )

    extension = Path(filename).suffix.lower()
    try:
        content = file.file.read(MAX_DOCUMENT_SIZE_BYTES + 1)
    finally:
        file.file.close()

    if len(content) > MAX_DOCUMENT_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="O arquivo excede o limite permitido.",
        )
    if extension not in DOCUMENT_FORMATS or not _is_supported_content(
        extension,
        content,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo não é válido ou não é aceito.",
        )

    storage_key = uuid4().hex
    stored_path = _store_content(storage_key, content)
    document = Document(
        collection_id=collection.id,
        original_filename=filename,
        storage_key=storage_key,
        content_type=DOCUMENT_FORMATS[extension],
        size_bytes=len(content),
    )
    session.add(document)
    try:
        session.commit()
    except SQLAlchemyError:
        try:
            stored_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    session.refresh(document)
    return DocumentResponse.model_validate(document)


@router.get(
    "/{collection_id}/documents",
    response_model=list[DocumentResponse],
)
def list_documents(
    collection_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[DocumentResponse]:
    collection = _get_owned_collection(collection_id, user, session)
    documents = session.scalars(
        select(Document)
        .where(Document.collection_id == collection.id)
        .order_by(Document.created_at, Document.id)
    ).all()
    return [DocumentResponse.model_validate(document) for document in documents]


@router.delete(
    "/{collection_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_document(
    collection_id: UUID,
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    collection = _get_owned_collection(collection_id, user, session)
    document = session.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.collection_id == collection.id,
        )
    )
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento não encontrado.",
        )

    stored_path = _safe_storage_path(document.storage_key)
    session.delete(document)
    session.commit()
    try:
        stored_path.unlink(missing_ok=True)
    except OSError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível remover o arquivo armazenado.",
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)

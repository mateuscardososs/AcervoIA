import os
import stat
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Annotated, BinaryIO, Iterator
from urllib.parse import quote
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
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from acervo_ia.config import (
    DOCUMENT_FORMATS,
    DOCUMENT_STORAGE_DIRECTORY,
    MAX_DOCUMENT_SIZE_BYTES,
)
from acervo_ia.db.connection import get_db
from acervo_ia.db.models import Collection, Document, DocumentChunk, User
from acervo_ia.security import get_current_user
from acervo_ia.services.document_processing import (
    DocumentExtractionError,
    chunk_pages,
    extract_document_pages,
)

router = APIRouter(prefix="/collections", tags=["documents"])


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    processing_status: str
    processing_error: str | None


class DocumentProcessingResponse(BaseModel):
    document_id: UUID
    processing_status: str
    chunk_count: int


def _stream_open_file(open_file: BinaryIO) -> Iterator[bytes]:
    try:
        while content := open_file.read(64 * 1024):
            yield content
    finally:
        open_file.close()


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


def _find_document_by_content_hash(
    session: Session,
    collection_id: UUID,
    content_sha256: str,
) -> Document | None:
    return session.scalar(
        select(Document).where(
            Document.collection_id == collection_id,
            Document.content_sha256 == content_sha256,
        )
    )


def _find_legacy_document_by_content(
    session: Session,
    collection_id: UUID,
    content_sha256: str,
    content: bytes,
) -> Document | None:
    """Hash same-size legacy files lazily so pre-migration rows also deduplicate."""
    legacy_documents = session.scalars(
        select(Document)
        .where(
            Document.collection_id == collection_id,
            Document.content_sha256.is_(None),
            Document.size_bytes == len(content),
        )
        .order_by(Document.created_at, Document.id)
    ).all()
    for document in legacy_documents:
        try:
            legacy_path = _safe_storage_path(document.storage_key)
            if legacy_path.stat().st_size != len(content):
                continue
            legacy_content = legacy_path.read_bytes()
        except (HTTPException, OSError):
            continue

        if sha256(legacy_content).hexdigest() != content_sha256:
            continue

        document.content_sha256 = content_sha256
        try:
            session.commit()
        except IntegrityError:
            try:
                session.rollback()
                winner = _find_document_by_content_hash(
                    session,
                    collection_id,
                    content_sha256,
                )
            except SQLAlchemyError:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Não foi possível concluir o upload do arquivo.",
                ) from None
            if winner is not None:
                return winner
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Não foi possível concluir o upload do arquivo.",
            ) from None
        except SQLAlchemyError:
            try:
                session.rollback()
            except SQLAlchemyError:
                pass
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Não foi possível concluir o upload do arquivo.",
            ) from None
        return document
    return None


def _find_existing_document(
    session: Session,
    collection_id: UUID,
    content_sha256: str,
    content: bytes,
) -> Document | None:
    existing = _find_document_by_content_hash(
        session,
        collection_id,
        content_sha256,
    )
    if existing is not None:
        return existing
    return _find_legacy_document_by_content(
        session,
        collection_id,
        content_sha256,
        content,
    )


def _discard_stored_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _return_existing_document(
    document: Document,
    response: Response,
) -> DocumentResponse:
    response.status_code = status.HTTP_200_OK
    return DocumentResponse.model_validate(document)


@router.post(
    "/{collection_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {
            "model": DocumentResponse,
            "description": "Documento existente reutilizado por conteúdo idêntico.",
        }
    },
)
def upload_document(
    collection_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
    response: Response,
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

    content_sha256 = sha256(content).hexdigest()
    try:
        existing = _find_existing_document(
            session,
            collection.id,
            content_sha256,
            content,
        )
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível concluir o upload do arquivo.",
        ) from None
    if existing is not None:
        return _return_existing_document(existing, response)

    storage_key = uuid4().hex
    stored_path = _store_content(storage_key, content)
    document = Document(
        collection_id=collection.id,
        original_filename=filename,
        storage_key=storage_key,
        content_sha256=content_sha256,
        content_type=DOCUMENT_FORMATS[extension],
        size_bytes=len(content),
    )
    session.add(document)
    try:
        session.commit()
    except IntegrityError:
        try:
            session.rollback()
        except SQLAlchemyError:
            pass
        _discard_stored_file(stored_path)
        try:
            duplicate = _find_document_by_content_hash(
                session,
                collection.id,
                content_sha256,
            )
        except SQLAlchemyError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Não foi possível concluir o upload do arquivo.",
            ) from None
        if duplicate is not None:
            return _return_existing_document(duplicate, response)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível concluir o upload do arquivo.",
        ) from None
    except SQLAlchemyError:
        try:
            session.rollback()
        except SQLAlchemyError:
            pass
        _discard_stored_file(stored_path)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível concluir o upload do arquivo.",
        ) from None
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


@router.get(
    "/{collection_id}/documents/{document_id}/file",
    response_class=StreamingResponse,
    responses={
        status.HTTP_200_OK: {
            "description": "Arquivo original do documento.",
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
                "text/plain": {},
            },
        }
    },
)
def open_original_document(
    collection_id: UUID,
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
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
    try:
        descriptor = os.open(
            stored_path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        open_file = os.fdopen(descriptor, "rb")
        file_info = os.fstat(open_file.fileno())
        if not stat.S_ISREG(file_info.st_mode):
            open_file.close()
            raise FileNotFoundError
    except OSError:
        if "open_file" in locals() and not open_file.closed:
            open_file.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="O arquivo original deste documento não está disponível.",
        ) from None

    filename = document.original_filename.replace("\\", "/").rsplit("/", 1)[-1]
    filename = "".join(
        character
        for character in filename
        if ord(character) >= 32 and ord(character) != 127
    ).strip() or str(document.id)
    media_type = (
        document.content_type
        if document.content_type in DOCUMENT_FORMATS.values()
        else "application/octet-stream"
    )
    disposition = "inline" if media_type == "application/pdf" else "attachment"
    headers = {
        "Content-Disposition": (
            f"{disposition}; filename*=UTF-8''{quote(filename, safe='')}"
        ),
        "Content-Length": str(file_info.st_size),
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(
        _stream_open_file(open_file),
        media_type=media_type,
        headers=headers,
    )


@router.post(
    "/{collection_id}/documents/{document_id}/process",
    response_model=DocumentProcessingResponse,
)
def process_document(
    collection_id: UUID,
    document_id: UUID,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> DocumentProcessingResponse:
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
    document.processing_status = "processing"
    document.processing_error = None
    session.commit()

    try:
        pages = extract_document_pages(stored_path, document.content_type)
        chunks = chunk_pages(pages)
    except (DocumentExtractionError, ValueError):
        return _fail_document_processing(document, session)

    if not chunks:
        return _fail_document_processing(document, session)

    session.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
    )
    session.add_all(
        DocumentChunk(
            document_id=document.id,
            position=position,
            page_number=chunk.page_number,
            content=chunk.content,
        )
        for position, chunk in enumerate(chunks)
    )
    document.processing_status = "completed"
    document.processing_error = None
    session.commit()
    return DocumentProcessingResponse(
        document_id=document.id,
        processing_status=document.processing_status,
        chunk_count=len(chunks),
    )


def _fail_document_processing(
    document: Document,
    session: Session,
) -> DocumentProcessingResponse:
    session.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
    )
    document.processing_status = "failed"
    document.processing_error = "Não foi possível extrair texto do documento."
    session.commit()
    raise HTTPException(
        status_code=422,
        detail=document.processing_error,
    ) from None

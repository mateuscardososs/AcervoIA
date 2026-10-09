"""Durable document-task worker.

Run with ``python -m acervo_ia.worker``. Task and document content are never
written to logs; only opaque task identifiers and lifecycle metadata are logged.
"""

import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from acervo_ia import config
from acervo_ia.db.connection import get_engine
from acervo_ia.db.models import Collection, Document, DocumentChunk, DocumentTask, User
from acervo_ia.services.document_processing import (
    DocumentExtractionError,
    chunk_pages,
    extract_document_pages,
)
from acervo_ia.services.embeddings import (
    EmbeddingDimensionError,
    EmbeddingServiceError,
    generate_embeddings,
)

logger = logging.getLogger("acervo_ia.worker")
MAX_ATTEMPTS = 3
LEASE_DURATION = timedelta(minutes=15)
POLL_INTERVAL_SECONDS = 2


class TaskOwnershipError(RuntimeError):
    """Stored task relationships no longer match their owner scope."""


def _now() -> datetime:
    return datetime.now(UTC)


def _factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def _safe_storage_path(storage_key: str) -> Path:
    if len(storage_key) != 32 or any(c not in "0123456789abcdef" for c in storage_key):
        raise DocumentExtractionError
    return config.DOCUMENT_STORAGE_DIRECTORY / storage_key


def _set_progress(
    factory: sessionmaker[Session], task_id: UUID, progress: int
) -> None:
    with factory() as session:
        task = session.get(DocumentTask, task_id)
        if task is None or task.status != "processing":
            return
        task.progress = progress
        task.lease_expires_at = _now() + LEASE_DURATION
        session.commit()


def _claim(factory: sessionmaker[Session], task_id: UUID) -> DocumentTask | None:
    now = _now()
    with factory() as session:
        task = session.scalar(
            select(DocumentTask)
            .where(DocumentTask.id == task_id)
            .with_for_update(skip_locked=True)
        )
        if task is None or task.status in {"completed", "failed"}:
            return None
        if task.status == "processing" and task.lease_expires_at is not None:
            lease = task.lease_expires_at
            if lease.tzinfo is None:
                lease = lease.replace(tzinfo=UTC)
            if lease > now:
                return None
        owned = _load_owned_document(session, task.id)
        if owned is None:
            task.status = "failed"
            task.progress = 0
            task.error = "Não foi possível concluir o processamento do documento."
            task.lease_expires_at = None
            session.commit()
            return None
        if task.attempt_count >= MAX_ATTEMPTS:
            task.status = "failed"
            task.progress = 0
            task.error = "Não foi possível concluir o processamento do documento."
            task.lease_expires_at = None
            if task.task_type == "process":
                _task, document = owned
                session.execute(
                    delete(DocumentChunk).where(
                        DocumentChunk.document_id == document.id
                    )
                )
                document.processing_status = "failed"
                document.processing_error = task.error
            session.commit()
            return None
        task.status = "processing"
        task.attempt_count += 1
        task.progress = max(task.progress, 1)
        task.error = None
        task.lease_expires_at = now + LEASE_DURATION
        task.updated_at = now
        if task.task_type == "process":
            _task, document = owned
            document.processing_status = "processing"
            document.processing_error = None
        session.commit()
        session.refresh(task)
        return task


def _load_owned_document(
    session: Session, task_id: UUID
) -> tuple[DocumentTask, Document] | None:
    rows = session.execute(
        select(DocumentTask, Document)
        .join(Document, Document.id == DocumentTask.document_id)
        .join(Collection, Collection.id == Document.collection_id)
        .join(User, User.id == Collection.owner_id)
        .where(
            DocumentTask.id == task_id,
            DocumentTask.document_id == Document.id,
            DocumentTask.collection_id == Collection.id,
            DocumentTask.owner_id == User.id,
            Document.collection_id == Collection.id,
        )
    ).first()
    if rows is None:
        return None
    return rows[0], rows[1]


def _process_document(
    factory: sessionmaker[Session], task_id: UUID
) -> int:
    with factory() as session:
        owned = _load_owned_document(session, task_id)
        if owned is None:
            raise TaskOwnershipError
        task, document = owned
        path = _safe_storage_path(document.storage_key)
        content_type = document.content_type

    pages = extract_document_pages(path, content_type)
    chunks = chunk_pages(pages)
    if not chunks:
        raise DocumentExtractionError
    _set_progress(factory, task_id, 70)
    with factory() as session:
        owned = _load_owned_document(session, task_id)
        if owned is None:
            raise TaskOwnershipError
        task, document = owned
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
        task.result_count = len(chunks)
        session.commit()
    return len(chunks)


def _embed_document(factory: sessionmaker[Session], task_id: UUID) -> tuple[int, str]:
    with factory() as session:
        owned = _load_owned_document(session, task_id)
        if owned is None:
            raise TaskOwnershipError
        _task, document = owned
        if document.processing_status != "completed":
            raise DocumentExtractionError
        chunks = session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.position)
        ).all()
        if not chunks:
            raise DocumentExtractionError
        chunk_ids = [chunk.id for chunk in chunks]
        contents = [chunk.content for chunk in chunks]

    _set_progress(factory, task_id, 15)
    vectors = generate_embeddings(contents, model=config.OLLAMA_EMBEDDING_MODEL)
    if len(vectors) != len(chunk_ids):
        raise EmbeddingServiceError
    _set_progress(factory, task_id, 75)
    with factory() as session:
        owned = _load_owned_document(session, task_id)
        if owned is None:
            raise TaskOwnershipError
        task, _document = owned
        chunks_by_id = {
            chunk.id: chunk
            for chunk in session.scalars(
                select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids))
            ).all()
        }
        if len(chunks_by_id) != len(chunk_ids):
            raise EmbeddingServiceError
        for chunk_id, vector in zip(chunk_ids, vectors, strict=True):
            chunk = chunks_by_id[chunk_id]
            chunk.embedding = vector
            chunk.embedding_model = config.OLLAMA_EMBEDDING_MODEL
        task.result_count = len(chunk_ids)
        task.embedding_model = config.OLLAMA_EMBEDDING_MODEL
        session.commit()
    return len(chunk_ids), config.OLLAMA_EMBEDDING_MODEL


def _finish(
    factory: sessionmaker[Session],
    task_id: UUID,
    *,
    count: int | None = None,
    model: str | None = None,
) -> None:
    with factory() as session:
        task = session.get(DocumentTask, task_id)
        if task is None:
            return
        task.status = "completed"
        task.progress = 100
        task.error = None
        task.result_count = count if count is not None else task.result_count
        task.embedding_model = model if model is not None else task.embedding_model
        task.lease_expires_at = None
        task.updated_at = _now()
        session.commit()


def _fail(
    factory: sessionmaker[Session], task_id: UUID, *, retryable: bool,
    update_document: bool = True,
) -> str:
    with factory() as session:
        task = session.get(DocumentTask, task_id)
        if task is None:
            return "missing"
        terminal = not retryable or task.attempt_count >= MAX_ATTEMPTS
        task.status = "failed" if terminal else "pending"
        task.error = (
            "Não foi possível extrair texto do documento."
            if task.task_type == "process"
            else "Não foi possível gerar os vetores do documento."
        ) if terminal else None
        task.progress = 0 if not terminal else task.progress
        task.lease_expires_at = None
        task.updated_at = _now()
        if terminal and update_document and task.task_type == "process":
            owned = _load_owned_document(session, task_id)
            if owned is not None:
                _task, document = owned
                session.execute(
                    delete(DocumentChunk).where(
                        DocumentChunk.document_id == document.id
                    )
                )
                document.processing_status = "failed"
                document.processing_error = task.error
        session.commit()
        return task.status


def run_task(
    task_id: str | UUID,
    *,
    session_factory: sessionmaker[Session] | None = None,
) -> bool:
    """Claim and execute one task; returns whether this call claimed it."""
    factory = session_factory or _factory()
    parsed_id = task_id if isinstance(task_id, UUID) else UUID(task_id)
    task = _claim(factory, parsed_id)
    if task is None:
        return False
    task_type = task.task_type
    attempt = task.attempt_count
    try:
        if task_type == "process":
            count = _process_document(factory, parsed_id)
            _finish(factory, parsed_id, count=count)
        elif task_type == "embeddings":
            count, model = _embed_document(factory, parsed_id)
            _finish(factory, parsed_id, count=count, model=model)
        else:
            _fail(factory, parsed_id, retryable=False)
            return True
    except TaskOwnershipError:
        result = _fail(factory, parsed_id, retryable=False, update_document=False)
        logger.warning("task=%s type=%s attempt=%d state=%s", parsed_id, task_type, attempt, result)
    except EmbeddingDimensionError:
        result = _fail(factory, parsed_id, retryable=False)
        logger.warning("task=%s type=%s attempt=%d state=%s", parsed_id, task_type, attempt, result)
    except EmbeddingServiceError:
        result = _fail(factory, parsed_id, retryable=True)
        logger.warning("task=%s type=%s attempt=%d state=%s", parsed_id, task_type, attempt, result)
    except (DocumentExtractionError, ValueError, OSError):
        result = _fail(factory, parsed_id, retryable=False)
        logger.warning("task=%s type=%s attempt=%d state=%s", parsed_id, task_type, attempt, result)
    except Exception:
        result = _fail(factory, parsed_id, retryable=True)
        logger.warning("task=%s type=%s attempt=%d state=%s", parsed_id, task_type, attempt, result)
    else:
        logger.info("task=%s type=%s attempt=%d state=completed", parsed_id, task_type, attempt)
    return True


def run_worker(
    *,
    session_factory: sessionmaker[Session] | None = None,
    poll_interval: float = POLL_INTERVAL_SECONDS,
    stop: Callable[[], bool] | None = None,
) -> None:
    factory = session_factory or _factory()
    should_stop = stop or (lambda: False)
    while not should_stop():
        try:
            with factory() as session:
                candidate = session.scalar(
                    select(DocumentTask.id)
                    .where(
                        or_(
                            DocumentTask.status == "pending",
                            (DocumentTask.status == "processing")
                            & (DocumentTask.lease_expires_at <= _now()),
                        ),
                    )
                    .order_by(DocumentTask.created_at, DocumentTask.id)
                    .limit(1)
                )
        except Exception:
            logger.error("worker poll failed; database details suppressed")
            time.sleep(poll_interval)
            continue
        if candidate is None:
            time.sleep(poll_interval)
            continue
        try:
            run_task(candidate, session_factory=factory)
        except Exception:
            logger.error("worker task dispatch failed; task details suppressed")
            time.sleep(poll_interval)


def _configure_compose_database_url() -> None:
    host = os.getenv("WORKER_DATABASE_HOST")
    if not host:
        return
    url = URL.create(
        "postgresql+psycopg",
        username=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=host,
        port=5432,
        database=os.getenv("POSTGRES_DB"),
    )
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)


def main() -> None:
    logging.basicConfig(level=os.getenv("WORKER_LOG_LEVEL", "INFO"))
    _configure_compose_database_url()
    try:
        run_worker()
    except Exception:
        logger.error("worker stopped; internal error details suppressed")


if __name__ == "__main__":
    main()

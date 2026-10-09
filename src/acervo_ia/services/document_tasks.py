from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from acervo_ia.db.models import Collection, Document, DocumentTask, User


class ActiveDocumentTaskError(RuntimeError):
    """Another kind of task currently owns the document's processing slot."""


class DocumentTaskQueueError(RuntimeError):
    """The task could not be stored safely; contains no database details."""


def enqueue_document_task(
    session: Session,
    *,
    document: Document,
    collection: Collection,
    user: User,
    task_type: str,
) -> DocumentTask:
    try:
        active = session.scalar(
            select(DocumentTask).where(
                DocumentTask.document_id == document.id,
                DocumentTask.collection_id == collection.id,
                DocumentTask.owner_id == user.id,
                DocumentTask.status.in_(("pending", "processing")),
            )
        )
    except SQLAlchemyError:
        raise DocumentTaskQueueError from None
    if active is not None:
        if active.task_type != task_type:
            raise ActiveDocumentTaskError
        return active

    task = DocumentTask(
        document_id=document.id,
        collection_id=collection.id,
        owner_id=user.id,
        task_type=task_type,
        status="pending",
        progress=0,
        attempt_count=0,
    )
    session.add(task)
    if task_type == "process":
        document.processing_status = "pending"
        document.processing_error = None
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        try:
            winner = session.scalar(
                select(DocumentTask).where(
                    DocumentTask.document_id == document.id,
                    DocumentTask.collection_id == collection.id,
                    DocumentTask.owner_id == user.id,
                    DocumentTask.status.in_(("pending", "processing")),
                )
            )
        except SQLAlchemyError:
            raise DocumentTaskQueueError from None
        if winner is not None and winner.task_type == task_type:
            return winner
        if winner is not None:
            raise ActiveDocumentTaskError from None
        raise DocumentTaskQueueError from None
    except SQLAlchemyError:
        session.rollback()
        raise DocumentTaskQueueError from None
    session.refresh(task)
    return task

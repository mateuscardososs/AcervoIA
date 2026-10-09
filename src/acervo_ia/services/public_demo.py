"""Idempotent seed for the read-only public portfolio account."""

import secrets
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from acervo_ia import config, demo
from acervo_ia.db.models import Collection, Document, User
from acervo_ia.security import hash_password
from acervo_ia.services import storage
from acervo_ia.services.document_tasks import enqueue_document_task
from acervo_ia.services.document_tasks import DocumentTaskQueueError

PUBLIC_COLLECTION_NAME = config.DEMO_COLLECTION_NAME
PUBLIC_COLLECTION_DESCRIPTION = (
    "Demonstração de portfólio com conteúdo inteiramente fictício. "
    "Não representa equipamentos, procedimentos ou recomendações reais."
)


class PublicDemoSeedError(RuntimeError):
    """A safe, operator-readable demo seed failure."""


def seed_public_demo(session: Session) -> tuple[str, int]:
    contents: dict[str, bytes] = {}
    try:
        contents = {
            filename: (demo.DEMO_SOURCE_DIRECTORY / filename).read_bytes()
            for filename in demo.DEMO_SOURCE_FILES
        }
    except OSError:
        raise PublicDemoSeedError("Os documentos fictícios da demonstração não estão disponíveis.") from None

    account_email = config.DEMO_ACCOUNT_EMAIL.strip().lower()
    if not account_email or "@" not in account_email:
        raise PublicDemoSeedError("O e-mail operacional da demonstração não é válido.")
    user = session.scalar(select(User).where(User.email == account_email))
    if user is not None and not user.is_demo:
        raise PublicDemoSeedError("O e-mail da demonstração já pertence a uma conta comum.")
    if user is not None:
        existing_collections = session.scalars(
            select(Collection).where(Collection.owner_id == user.id)
        ).all()
        if any(item.name != PUBLIC_COLLECTION_NAME for item in existing_collections):
            raise PublicDemoSeedError("A conta demo contém dados fora do escopo público.")
        existing_names = session.scalars(
            select(Document.original_filename)
            .join(Collection, Collection.id == Document.collection_id)
            .where(Collection.owner_id == user.id)
        ).all()
        if any(not name.startswith("[DEMO FICTÍCIO] ") for name in existing_names):
            raise PublicDemoSeedError("A conta demo contém documentos fora do escopo fictício.")
    if user is None:
        # No stable password exists; public access is exclusively through the
        # gated short-lived session endpoint.
        user = User(
            email=account_email,
            password_hash=hash_password(secrets.token_urlsafe(48)),
            is_demo=True,
        )
        session.add(user)
        session.flush()
    collection = session.scalar(
        select(Collection).where(
            Collection.owner_id == user.id,
            Collection.name == PUBLIC_COLLECTION_NAME,
        )
    )
    if collection is None:
        collection = Collection(
            owner_id=user.id,
            name=PUBLIC_COLLECTION_NAME,
            description=PUBLIC_COLLECTION_DESCRIPTION,
        )
        session.add(collection)
        session.flush()

    created_storage_keys: list[str] = []
    added = 0
    try:
        for filename, content in contents.items():
            digest = sha256(content).hexdigest()
            existing = session.scalar(
                select(Document.id).where(
                    Document.collection_id == collection.id,
                    Document.content_sha256 == digest,
                )
            )
            if existing is not None:
                continue
            key = uuid4().hex
            storage.store(key, content)
            created_storage_keys.append(key)
            session.add(
                Document(
                    collection_id=collection.id,
                    original_filename=f"[DEMO FICTÍCIO] {Path(filename).name}",
                    storage_key=key,
                    content_sha256=digest,
                    content_type="text/plain",
                    size_bytes=len(content),
                    processing_status="pending",
                )
            )
            added += 1
        session.commit()
    except (SQLAlchemyError, storage.StorageUnavailable):
        session.rollback()
        for key in created_storage_keys:
            try:
                storage.delete(key)
            except storage.StorageUnavailable:
                pass
        raise PublicDemoSeedError("Não foi possível preparar os dados da demonstração.") from None
    try:
        pending_documents = session.scalars(
            select(Document).where(
                Document.collection_id == collection.id,
                Document.processing_status == "pending",
            )
        ).all()
        for document in pending_documents:
            enqueue_document_task(
                session,
                document=document,
                collection=collection,
                user=user,
                task_type="process",
            )
    except (SQLAlchemyError, DocumentTaskQueueError):
        session.rollback()
        raise PublicDemoSeedError(
            "Dados fictícios criados, mas não foi possível enfileirar o processamento."
        ) from None
    return account_email, added

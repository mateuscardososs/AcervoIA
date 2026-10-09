from collections.abc import Sequence
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from acervo_ia.db.models import Document


def validate_document_filter(
    session: Session,
    *,
    collection_id: UUID,
    document_ids: Sequence[UUID],
) -> list[UUID] | None:
    """Return the requested scope after verifying every ID belongs to collection."""
    if not document_ids:
        return None

    selected_ids = list(dict.fromkeys(document_ids))
    found_ids = set(
        session.scalars(
            select(Document.id).where(
                Document.collection_id == collection_id,
                Document.id.in_(selected_ids),
            )
        ).all()
    )
    if found_ids != set(selected_ids):
        raise HTTPException(
            status_code=404,
            detail="Um ou mais documentos não foram encontrados nesta coleção.",
        )
    return selected_ids

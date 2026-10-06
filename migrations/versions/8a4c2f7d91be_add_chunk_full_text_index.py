"""add PostgreSQL full-text GIN index to document chunks

Revision ID: 8a4c2f7d91be
Revises: 4df6a1c839ab
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "8a4c2f7d91be"
down_revision: Union[str, Sequence[str], None] = "4df6a1c839ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_document_chunks_content_fts "
        "ON document_chunks USING GIN (to_tsvector('simple', content))"
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_content_fts", table_name="document_chunks")

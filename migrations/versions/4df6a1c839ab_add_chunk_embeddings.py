"""add pgvector embeddings to document chunks

Revision ID: 4df6a1c839ab
Revises: b5fd0931c786
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR


# revision identifiers, used by Alembic.
revision: str = "4df6a1c839ab"
down_revision: Union[str, Sequence[str], None] = "b5fd0931c786"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "document_chunks",
        sa.Column("embedding", VECTOR(768), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
    )
    op.create_check_constraint(
        "ck_document_chunks_embedding_model_pair",
        "document_chunks",
        "(embedding IS NULL) = (embedding_model IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_chunks_embedding_model_pair",
        "document_chunks",
        type_="check",
    )
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "embedding")
    # Keep the shared PostgreSQL extension installed; other tables may use it.

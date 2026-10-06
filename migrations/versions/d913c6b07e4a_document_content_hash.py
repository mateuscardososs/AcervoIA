"""add per-collection document content hash

Revision ID: d913c6b07e4a
Revises: 8a4c2f7d91be
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d913c6b07e4a"
down_revision: Union[str, Sequence[str], None] = "8a4c2f7d91be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_documents_collection_content_sha256",
        "documents",
        ["collection_id", "content_sha256"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_documents_collection_content_sha256",
        "documents",
        type_="unique",
    )
    op.drop_column("documents", "content_sha256")

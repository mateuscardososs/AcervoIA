"""add document processing state and text chunks

Revision ID: b5fd0931c786
Revises: c01596ac114e
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b5fd0931c786"
down_revision: Union[str, Sequence[str], None] = "c01596ac114e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "processing_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("processing_error", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_documents_processing_status",
        "documents",
        "processing_status IN ('pending', 'processing', 'completed', 'failed')",
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_document_chunks_position"),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_document_chunks_page_number",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "position",
            name="uq_document_chunks_document_position",
        ),
    )
    op.create_index(
        op.f("ix_document_chunks_document_id"),
        "document_chunks",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_document_chunks_document_id"),
        table_name="document_chunks",
    )
    op.drop_table("document_chunks")
    op.drop_constraint(
        "ck_documents_processing_status",
        "documents",
        type_="check",
    )
    op.drop_column("documents", "processing_error")
    op.drop_column("documents", "processing_status")

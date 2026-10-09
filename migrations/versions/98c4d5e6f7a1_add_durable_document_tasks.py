"""add durable document processing tasks

Revision ID: 98c4d5e6f7a1
Revises: a620f9d34b72
Create Date: 2026-10-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "98c4d5e6f7a1"
down_revision: Union[str, Sequence[str], None] = "a620f9d34b72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "task_type IN ('process', 'embeddings')",
            name="ck_document_tasks_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_document_tasks_status",
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name="ck_document_tasks_progress"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_document_tasks_attempts"),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_tasks_document_id", "document_tasks", ["document_id"])
    op.create_index("ix_document_tasks_collection_id", "document_tasks", ["collection_id"])
    op.create_index("ix_document_tasks_owner_id", "document_tasks", ["owner_id"])
    op.create_index(
        "ix_document_tasks_status_lease",
        "document_tasks",
        ["status", "lease_expires_at"],
    )
    op.create_index(
        "uq_document_tasks_active_document",
        "document_tasks",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
        sqlite_where=sa.text("status IN ('pending', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index("uq_document_tasks_active_document", table_name="document_tasks")
    op.drop_index("ix_document_tasks_status_lease", table_name="document_tasks")
    op.drop_index("ix_document_tasks_owner_id", table_name="document_tasks")
    op.drop_index("ix_document_tasks_collection_id", table_name="document_tasks")
    op.drop_index("ix_document_tasks_document_id", table_name="document_tasks")
    op.drop_table("document_tasks")

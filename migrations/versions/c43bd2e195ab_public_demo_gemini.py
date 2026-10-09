"""public demo controls, rate limits, and embedding provider tags

Revision ID: c43bd2e195ab
Revises: 98c4d5e6f7a1
Create Date: 2026-10-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c43bd2e195ab"
down_revision: Union[str, Sequence[str], None] = "98c4d5e6f7a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_demo", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "document_chunks",
        sa.Column("embedding_provider", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "document_tasks",
        sa.Column("embedding_provider", sa.String(length=20), nullable=True),
    )
    op.execute(
        "UPDATE document_chunks SET embedding_provider = 'ollama' "
        "WHERE embedding IS NOT NULL"
    )
    op.drop_constraint(
        "ck_document_chunks_embedding_model_pair",
        "document_chunks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_document_chunks_embedding_metadata_pair",
        "document_chunks",
        "(embedding IS NULL) = (embedding_model IS NULL) AND "
        "(embedding IS NULL) = (embedding_provider IS NULL)",
    )
    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "usage_buckets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=30), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("count >= 0", name="ck_usage_bucket_count"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope", "key_hash", "window_start", name="uq_usage_bucket_window"
        ),
    )
    op.create_index("ix_usage_buckets_window", "usage_buckets", ["window_start"])
    op.execute(
        "INSERT INTO runtime_settings (key, value) VALUES ('public_demo_enabled', 'false')"
    )
    op.execute(
        "INSERT INTO runtime_settings (key, value) VALUES ('gemini_enabled', 'false')"
    )


def downgrade() -> None:
    op.drop_index("ix_usage_buckets_window", table_name="usage_buckets")
    op.drop_table("usage_buckets")
    op.drop_table("runtime_settings")
    op.drop_constraint(
        "ck_document_chunks_embedding_metadata_pair",
        "document_chunks",
        type_="check",
    )
    op.drop_column("document_chunks", "embedding_provider")
    op.drop_column("document_tasks", "embedding_provider")
    op.create_check_constraint(
        "ck_document_chunks_embedding_model_pair",
        "document_chunks",
        "(embedding IS NULL) = (embedding_model IS NULL)",
    )
    op.drop_column("users", "is_demo")

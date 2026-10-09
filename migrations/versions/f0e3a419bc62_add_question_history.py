"""add per-collection question history

Revision ID: f0e3a419bc62
Revises: d913c6b07e4a
Create Date: 2026-10-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f0e3a419bc62"
down_revision: Union[str, Sequence[str], None] = "d913c6b07e4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "question_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("strategy", sa.String(length=10), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "strategy IN ('vector', 'text', 'hybrid')",
            name="ck_question_history_strategy",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_question_history_collection_created_at",
        "question_history",
        ["collection_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_question_history_collection_created_at",
        table_name="question_history",
    )
    op.drop_table("question_history")

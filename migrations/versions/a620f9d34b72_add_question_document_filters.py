"""preserve document filters in question history

Revision ID: a620f9d34b72
Revises: f0e3a419bc62
Create Date: 2026-10-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a620f9d34b72"
down_revision: Union[str, Sequence[str], None] = "f0e3a419bc62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "question_history",
        sa.Column(
            "document_ids",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("question_history", "document_ids")

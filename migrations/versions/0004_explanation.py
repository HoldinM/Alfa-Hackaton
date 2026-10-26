"""Объяснение решения простыми словами: assessments.explanation.

Revision ID: 0004_explanation
Revises: 0003_own_company
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_explanation"
down_revision = "0003_own_company"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assessments", sa.Column("explanation", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("assessments", "explanation")

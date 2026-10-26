"""Заключение для аналитика банка: assessments.analyst_explanation.

Revision ID: 0005_analyst_explanation
Revises: 0004_explanation
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_analyst_explanation"
down_revision = "0004_explanation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assessments", sa.Column("analyst_explanation", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("assessments", "analyst_explanation")

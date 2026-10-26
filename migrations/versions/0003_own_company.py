"""Своя компания: профиль, введённый пользователем вместо данных реестров.

Revision ID: 0003_own_company
Revises: 0002_metrics
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_own_company"
down_revision = "0002_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("applications", sa.Column("company_profile", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("applications", "company_profile")

"""Метрики: время решения ML и отзывы клиентов о понятности решения.

Revision ID: 0002_metrics
Revises: 0001_initial
Create Date: 2026-10-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_metrics"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assessments", sa.Column("duration_ms", sa.Integer(), nullable=True))
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("application_id", sa.Integer(),
                  sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("decision_clear", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    )
    op.create_index("ix_feedback_application_id", "feedback", ["application_id"])


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_column("assessments", "duration_ms")

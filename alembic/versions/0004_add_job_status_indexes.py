"""Add database indexes for job status queries.

Revision ID: 0004_add_job_status_indexes
Revises: 0003_add_current_step
Create Date: 2026-04-04
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0004_add_job_status_indexes"
down_revision = "0003_add_current_step"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add indexes to improve job status query performance."""
    op.create_index("idx_articles_job_id", "articles", ["job_id"])
    op.create_index("idx_articles_status", "articles", ["status"])


def downgrade() -> None:
    """Remove job status indexes."""
    op.drop_index("idx_articles_status", table_name="articles")
    op.drop_index("idx_articles_job_id", table_name="articles")

"""Add current_step field for multi-step LLM pipeline.

Revision ID: 0003_add_current_step
Revises: 0002_add_md_content_seo_score
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_add_current_step"
down_revision = "0002_add_md_content_seo_score"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add current_step column to articles table."""
    op.add_column("articles", sa.Column("current_step", sa.String(50), nullable=True))


def downgrade() -> None:
    """Remove current_step column from articles table."""
    op.drop_column("articles", "current_step")

"""Add md_content and seo_score fields to articles table.

Revision ID: 0002_add_md_content_seo_score
Revises: 0001_initial
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_add_md_content_seo_score"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add md_content and seo_score columns to articles table."""
    op.add_column("articles", sa.Column("md_content", sa.Text(), nullable=True))
    op.add_column("articles", sa.Column("seo_score", sa.Float(), nullable=True))


def downgrade() -> None:
    """Remove md_content and seo_score columns from articles table."""
    op.drop_column("articles", "seo_score")
    op.drop_column("articles", "md_content")

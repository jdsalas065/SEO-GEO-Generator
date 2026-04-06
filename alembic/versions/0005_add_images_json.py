"""Add images_json field to articles.

Revision ID: 0005_add_images_json
Revises: 0004_add_job_status_indexes
Create Date: 2026-04-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0005_add_images_json"
down_revision = "0004_add_job_status_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add images_json JSONB column to articles."""
    op.add_column(
        "articles",
        sa.Column("images_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Remove images_json column from articles."""
    op.drop_column("articles", "images_json")

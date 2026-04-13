"""Add outline field to articles.

Revision ID: 0006_add_article_outline
Revises: 0005_add_images_json
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0006_add_article_outline"
down_revision = "0005_add_images_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add outline JSON column to articles."""
    op.add_column(
        "articles",
        sa.Column(
            "outline",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove outline column from articles."""
    op.drop_column("articles", "outline")
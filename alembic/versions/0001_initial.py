"""Initial schema: jobs and articles tables.

Revision ID: 0001_initial
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Enums ---
    # Asyncpg can still raise duplicate type errors in some checkfirst flows,
    # so create enums with an explicit duplicate-object guard.
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE job_status AS ENUM ('pending', 'running', 'done', 'failed');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE article_status AS ENUM (
                'queued',
                'generating',
                'pending_review',
                'approved',
                'rejected'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END
        $$;
        """
    )

    # --- jobs ---
    op.create_table(
        "jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "running",
                "done",
                "failed",
                name="job_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("source_filename", sa.String(255), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # --- articles ---
    op.create_table(
        "articles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("topic", sa.String(512), nullable=False),
        sa.Column("keyword", sa.String(255), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "queued",
                "generating",
                "pending_review",
                "approved",
                "rejected",
                name="article_status",
                create_type=False,
            ),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # Indexes
    op.create_index("ix_articles_job_id", "articles", ["job_id"])
    op.create_index("ix_articles_status", "articles", ["status"])


def downgrade() -> None:
    op.drop_table("articles")
    op.drop_table("jobs")
    op.execute("DROP TYPE IF EXISTS article_status")
    op.execute("DROP TYPE IF EXISTS job_status")

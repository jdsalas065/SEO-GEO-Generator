"""Pydantic v2 schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import ArticleStatus, JobStatus


# ---------------------------------------------------------------------------
# Job schemas
# ---------------------------------------------------------------------------


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: JobStatus
    source_filename: str
    total: int
    done: int
    failed: int
    created_at: datetime
    updated_at: datetime


class JobListOut(JobOut):
    """Summary row for GET /jobs with timeout visibility."""
    percent: int = Field(..., description="Completion percentage (done+failed)/total")
    timeout_count: int = Field(..., description="Number of timed-out articles in this job")


# ---------------------------------------------------------------------------
# Job status polling schemas
# ---------------------------------------------------------------------------


class JobProgress(BaseModel):
    """Progress metrics for a job."""
    total: int = Field(..., description="Total number of articles")
    done: int = Field(..., description="Number of completed articles")
    failed: int = Field(..., description="Number of failed articles")
    percent: int = Field(..., description="Percentage complete (0-100)")


class ArticleStatusItem(BaseModel):
    """Status of a single article in a job."""
    article_id: uuid.UUID
    topic: str
    status: ArticleStatus
    current_step: Optional[str] = Field(None, description="Current LLM step: outline, writing, seo_check")
    seo_score: Optional[float] = Field(None, description="SEO score 0.0-1.0")
    word_count: Optional[int] = Field(None, description="Article word count")


class JobDetailResponse(BaseModel):
    """Detailed job status with article list and progress."""
    job_id: uuid.UUID
    batch_name: str = Field(..., description="Source filename")
    status: JobStatus
    progress: JobProgress
    estimated_remaining_seconds: int = Field(..., description="Estimated seconds until completion")
    articles: list[ArticleStatusItem] = Field(..., description="Status of each article")
    timed_out_article_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="Timed-out article IDs that can be reworked",
    )
    timed_out_worker_ids: list[str] = Field(
        default_factory=list,
        description="Timed-out Celery task IDs for optional targeted reworker",
    )
    created_at: datetime
    updated_at: datetime


class ReworkerRequest(BaseModel):
    """Request body for manual requeue of timed-out workers."""
    worker_ids: list[str] = Field(..., min_length=1, description="List of timed-out Celery task IDs")
    review_note: Optional[str] = Field(
        None,
        description="Optional note passed into the next generation attempt",
    )


class JobReworkerRequest(BaseModel):
    """Request body for job-level timeout reworker."""
    review_note: Optional[str] = Field(
        None,
        description="Optional note passed into the next generation attempt",
    )
    limit: Optional[int] = Field(
        None,
        ge=1,
        description="Optional max number of timed-out articles to requeue",
    )


class ReworkerResultItem(BaseModel):
    """Result for one requested worker id."""
    worker_id: Optional[str] = None
    article_id: Optional[uuid.UUID] = None
    action: Literal[
        "requeued",
        "skipped_not_found",
        "skipped_not_timeout",
        "skipped_missing_worker_id",
    ]
    reason: Optional[str] = None


class ReworkerResponse(BaseModel):
    """Summary of manual reworker execution."""
    job_id: uuid.UUID
    requested: int
    requeued: int
    skipped: int
    results: list[ReworkerResultItem]


# ---------------------------------------------------------------------------
# Article schemas
# ---------------------------------------------------------------------------


class ArticleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    topic: str
    keyword: Optional[str]
    status: ArticleStatus
    current_step: Optional[str]
    content: Optional[str]
    md_content: Optional[str]
    seo_score: Optional[float]
    review_note: Optional[str]
    word_count: Optional[int]
    created_at: datetime
    updated_at: datetime


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    note: Optional[str] = Field(None, description="Required when action=reject")

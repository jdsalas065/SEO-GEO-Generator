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
    content: Optional[str]
    review_note: Optional[str]
    word_count: Optional[int]
    created_at: datetime
    updated_at: datetime


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    note: Optional[str] = Field(None, description="Required when action=reject")

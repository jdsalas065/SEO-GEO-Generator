"""Tests for job status polling API."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import Article, ArticleStatus, Job, JobStatus
from app.schemas import JobDetailResponse, JobProgress, ArticleStatusItem


class TestJobProgress:
    """Test JobProgress schema."""

    def test_progress_calculation(self) -> None:
        """Test progress percentage calculation."""
        progress = JobProgress(total=100, done=25, failed=5, percent=30)
        assert progress.percent == 30
        assert progress.total == 100

    def test_progress_zero_articles(self) -> None:
        """Test progress with zero articles."""
        progress = JobProgress(total=0, done=0, failed=0, percent=0)
        assert progress.percent == 0


class TestArticleStatusItem:
    """Test ArticleStatusItem schema."""

    def test_article_status_item_all_fields(self) -> None:
        """Test creating article status item with all fields."""
        article_id = uuid.uuid4()
        item = ArticleStatusItem(
            article_id=article_id,
            topic="Test Topic",
            status=ArticleStatus.generating,
            current_step="writing",
            seo_score=0.87,
            word_count=1200,
        )
        assert item.article_id == article_id
        assert item.current_step == "writing"
        assert item.seo_score == 0.87

    def test_article_status_item_optional_fields(self) -> None:
        """Test article status item with optional fields as None."""
        article_id = uuid.uuid4()
        item = ArticleStatusItem(
            article_id=article_id,
            topic="Test Topic",
            status=ArticleStatus.queued,
        )
        assert item.current_step is None
        assert item.seo_score is None


class TestJobDetailResponse:
    """Test JobDetailResponse schema."""

    def test_job_detail_response_complete(self) -> None:
        """Test creating complete job detail response."""
        job_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        
        articles = [
            ArticleStatusItem(
                article_id=uuid.uuid4(),
                topic="Article 1",
                status=ArticleStatus.approved,
                seo_score=0.9,
            ),
            ArticleStatusItem(
                article_id=uuid.uuid4(),
                topic="Article 2",
                status=ArticleStatus.generating,
                current_step="writing",
            ),
        ]
        
        progress = JobProgress(total=10, done=2, failed=0, percent=20)
        
        response = JobDetailResponse(
            job_id=job_id,
            batch_name="topics.xlsx",
            status=JobStatus.running,
            progress=progress,
            estimated_remaining_seconds=360,
            articles=articles,
            created_at=now,
            updated_at=now,
        )
        
        assert response.job_id == job_id
        assert len(response.articles) == 2
        assert response.progress.percent == 20
        assert response.estimated_remaining_seconds == 360


class TestEstimatedTimeCalculation:
    """Test estimated remaining time calculation logic."""

    def test_estimated_time_with_progress(self) -> None:
        """Test estimated time when articles are already done."""
        total = 10
        done = 5
        failed = 0
        
        elapsed_seconds = 100  # 5 articles took 100 seconds
        avg_per_article = elapsed_seconds / done  # 20 seconds per article
        remaining = total - done - failed  # 5 articles left
        estimated = avg_per_article * remaining  # 100 seconds
        
        assert estimated == 100
        assert int(estimated) == 100

    def test_estimated_time_no_progress(self) -> None:
        """Test estimated time with fallback when no articles done."""
        total = 10
        done = 0
        failed = 0
        
        # Fallback: 45 seconds per article
        remaining = total - failed
        estimated = remaining * 45
        
        assert estimated == 450

    def test_estimated_time_mostly_done(self) -> None:
        """Test estimated time calculation when almost done."""
        total = 100
        done = 95
        failed = 0
        elapsed_seconds = 3800  # 95 articles in 3800 seconds
        
        avg_per_article = elapsed_seconds / done  # ~40 seconds per article
        remaining = total - done - failed  # 5 articles left
        estimated = int(avg_per_article * remaining)  # 5 * 40 = 200
        
        assert estimated == 200


@pytest.mark.asyncio
async def test_job_status_endpoint_mock() -> None:
    """Test job status endpoint logic with mocks."""
    from app.routers.jobs import get_job_status
    from app.database import get_db
    
    # Create mock objects
    job_id = uuid.uuid4()
    article1_id = uuid.uuid4()
    article2_id = uuid.uuid4()
    
    # Mock articles
    article1 = MagicMock(spec=Article)
    article1.id = article1_id
    article1.topic = "Article 1"
    article1.status = ArticleStatus.approved
    article1.current_step = None
    article1.seo_score = 0.9
    article1.word_count = 1200
    
    article2 = MagicMock(spec=Article)
    article2.id = article2_id
    article2.topic = "Article 2"
    article2.status = ArticleStatus.generating
    article2.current_step = "writing"
    article2.seo_score = None
    article2.word_count = None

    article3_id = uuid.uuid4()
    article3 = MagicMock(spec=Article)
    article3.id = article3_id
    article3.topic = "Article 3"
    article3.status = ArticleStatus.rejected
    article3.current_step = None
    article3.seo_score = None
    article3.word_count = None
    article3.review_note = "Task timeout after 900s (soft limit reached)"
    article3.celery_task_id = "worker-timeout-3"
    
    # Mock job
    now = datetime.now(timezone.utc)
    past = now - timedelta(seconds=100)
    
    job = MagicMock(spec=Job)
    job.id = job_id
    job.source_filename = "topics.xlsx"
    job.status = JobStatus.running
    job.total = 10
    job.done = 2
    job.failed = 0
    job.created_at = past
    job.updated_at = now
    article1.review_note = None
    article1.celery_task_id = None
    article2.review_note = None
    article2.celery_task_id = "worker-running-2"
    job.articles = [article1, article2, article3]
    
    # Mock database - set up proper sync mock for scalar_one_or_none
    mock_scalars_result = MagicMock()
    mock_scalars_result.scalar_one_or_none = MagicMock(return_value=job)
    
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_scalars_result)
    
    # Call endpoint
    response = await get_job_status(job_id, mock_db)
    
    # Verify response
    assert isinstance(response, JobDetailResponse)
    assert response.job_id == job_id
    assert response.batch_name == "topics.xlsx"
    assert response.status == JobStatus.running
    assert response.progress.total == 10
    assert response.progress.done == 2
    assert response.progress.percent == 20
    assert len(response.articles) == 3
    assert response.articles[0].current_step is None
    assert response.articles[1].current_step == "writing"
    assert response.timed_out_article_ids == [article3_id]
    assert response.timed_out_worker_ids == ["worker-timeout-3"]
    # Should have calculated estimated time based on 100 seconds for 2 articles
    assert response.estimated_remaining_seconds > 0


@pytest.mark.asyncio
async def test_job_status_not_found() -> None:
    """Test job status endpoint returns 404 when job not found."""
    from fastapi import HTTPException
    from app.routers.jobs import get_job_status
    
    job_id = uuid.uuid4()
    
    # Mock database to return None
    mock_scalars_result = MagicMock()
    mock_scalars_result.scalar_one_or_none = MagicMock(return_value=None)
    
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_scalars_result)
    
    # Should raise 404
    with pytest.raises(HTTPException) as exc_info:
        await get_job_status(job_id, mock_db)
    
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()

"""Router: POST /jobs, GET /jobs and GET /jobs/{id}."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
import aiofiles.os
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import and_, case, func
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.input_parser import parse_input
from app.models import Article, ArticleStatus, Job, JobStatus
from app.schemas import (
    JobListOut,
    JobOut,
    JobDetailResponse,
    JobProgress,
    ArticleStatusItem,
    JobReworkerRequest,
    ReworkerRequest,
    ReworkerResponse,
    ReworkerResultItem,
)
from app.tasks import generate_article

router = APIRouter(prefix="/jobs", tags=["jobs"])

_UPLOAD_DIR = Path("uploads")
_TIMEOUT_NOTE_PREFIX = "Task timeout"


def _raise_if_schema_missing(exc: ProgrammingError) -> None:
    """Map missing-table DB errors to a user-facing migration hint."""
    if exc.orig is not None and exc.orig.__class__.__name__ == "UndefinedTableError":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database schema is missing. Run migration: alembic upgrade head",
        ) from exc
    raise exc


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> JobOut:
    """
    Upload an Excel (.xlsx) or JSON file containing article topics.
    Creates a batch job and queues Celery tasks for each topic.
    """
    try:
        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        # Persist upload to disk so input_parser can read it
        safe_name = Path(file.filename or "upload").name
        upload_path = _UPLOAD_DIR / safe_name
        async with aiofiles.open(upload_path, "wb") as out:
            content = await file.read()
            await out.write(content)

        # Parse topics
        try:
            topics = parse_input(upload_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to parse file: {exc}") from exc

        if not topics:
            raise HTTPException(status_code=400, detail="No topics found in the uploaded file")

        # Create Job record
        job = Job(
            source_filename=safe_name,
            status=JobStatus.running,
            total=len(topics),
        )
        db.add(job)
        await db.flush()  # get job.id

        # Create Article records and queue tasks
        for item in topics:
            article = Article(
                job_id=job.id,
                topic=item["topic"],
                keyword=item.get("keyword"),
                status=ArticleStatus.queued,
            )
            db.add(article)
            await db.flush()  # get article.id

            generate_article.delay(
                article_id=str(article.id),
                job_id=str(job.id),
                topic=item["topic"],
                keyword=item.get("keyword"),
            )

        await db.commit()
        await db.refresh(job)
        return JobOut.model_validate(job)
    except HTTPException:
        raise
    except ProgrammingError as exc:
        _raise_if_schema_missing(exc)


@router.get("", response_model=list[JobListOut])
async def list_jobs(db: AsyncSession = Depends(get_db)) -> list[JobListOut]:
    """Return all jobs ordered by newest first, including timeout summary."""
    try:
        timeout_condition = and_(
            Article.status == ArticleStatus.rejected,
            Article.review_note.is_not(None),
            Article.review_note.like("Task timeout%"),
        )

        stmt = (
            select(
                Job,
                func.sum(case((timeout_condition, 1), else_=0)).label("timeout_count"),
            )
            .outerjoin(Article, Article.job_id == Job.id)
            .group_by(Job.id)
            .order_by(Job.created_at.desc())
        )
        result = await db.execute(stmt)
        rows = result.all()

        data: list[JobListOut] = []
        for job, timeout_count in rows:
            percent = int(((job.done + job.failed) / job.total) * 100) if job.total > 0 else 0
            data.append(
                JobListOut(
                    id=job.id,
                    status=job.status,
                    source_filename=job.source_filename,
                    total=job.total,
                    done=job.done,
                    failed=job.failed,
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    percent=percent,
                    timeout_count=int(timeout_count or 0),
                )
            )

        return data
    except ProgrammingError as exc:
        _raise_if_schema_missing(exc)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> JobOut:
    """Return progress info for a batch job."""
    try:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobOut.model_validate(job)
    except ProgrammingError as exc:
        _raise_if_schema_missing(exc)


@router.get("/{job_id}/status", response_model=JobDetailResponse)
async def get_job_status(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> JobDetailResponse:
    """
    Return detailed job status with article progress and estimated time remaining.
    
    Uses selectinload to avoid N+1 queries.
    """
    try:
        # Fetch job with articles (eager load to avoid N+1)
        result = await db.execute(
            select(Job)
            .options(selectinload(Job.articles))
            .where(Job.id == job_id)
        )
        job = result.scalar_one_or_none()
        
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Build article status items
        article_items = []
        timed_out_article_ids: list[uuid.UUID] = []
        timed_out_worker_ids: list[str] = []
        for article in job.articles:
            article_items.append(
                ArticleStatusItem(
                    article_id=article.id,
                    topic=article.topic,
                    status=article.status,
                    current_step=article.current_step,
                    seo_score=article.seo_score,
                    word_count=article.word_count,
                )
            )
            if (
                article.status == ArticleStatus.rejected
                and article.review_note
                and article.review_note.startswith(_TIMEOUT_NOTE_PREFIX)
            ):
                timed_out_article_ids.append(article.id)
                if article.celery_task_id:
                    timed_out_worker_ids.append(article.celery_task_id)
        
        # Calculate progress
        total = job.total
        done = job.done
        failed = job.failed
        percent = int((done + failed) / total * 100) if total > 0 else 0
        
        progress = JobProgress(
            total=total,
            done=done,
            failed=failed,
            percent=percent,
        )
        
        # Calculate estimated remaining time
        now = datetime.now(timezone.utc)
        elapsed = (now - job.created_at).total_seconds()
        
        if done > 0:
            # Based on average time per article
            avg_time_per_article = elapsed / done
            remaining_articles = total - done - failed
            estimated_remaining = int(avg_time_per_article * remaining_articles)
        else:
            # Fallback: assume ~45 seconds per article if none completed yet
            remaining_articles = total - failed
            estimated_remaining = remaining_articles * 45
        
        # Ensure non-negative
        estimated_remaining = max(0, estimated_remaining)
        
        return JobDetailResponse(
            job_id=job.id,
            batch_name=job.source_filename,
            status=job.status,
            progress=progress,
            estimated_remaining_seconds=estimated_remaining,
            articles=article_items,
            timed_out_article_ids=timed_out_article_ids,
            timed_out_worker_ids=timed_out_worker_ids,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
    except ProgrammingError as exc:
        _raise_if_schema_missing(exc)


@router.post("/{job_id}/reworker", response_model=ReworkerResponse)
async def reworker_by_job(
    job_id: uuid.UUID,
    body: JobReworkerRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ReworkerResponse:
    """
    Requeue timed-out articles for a job.
    User only needs job_id; backend selects timed-out rows and requeues on demand.
    """
    try:
        payload = body or JobReworkerRequest()

        job_result = await db.execute(select(Job).where(Job.id == job_id))
        job = job_result.scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        timeout_stmt = select(Article).where(
            Article.job_id == job_id,
            Article.status == ArticleStatus.rejected,
            Article.review_note.is_not(None),
            Article.review_note.like(f"{_TIMEOUT_NOTE_PREFIX}%"),
        )
        if payload.limit is not None:
            timeout_stmt = timeout_stmt.limit(payload.limit)

        article_result = await db.execute(timeout_stmt)
        timed_out_articles = article_result.scalars().all()

        results: list[ReworkerResultItem] = []
        requeued_count = 0

        for article in timed_out_articles:
            worker_id = article.celery_task_id
            if not worker_id:
                results.append(
                    ReworkerResultItem(
                        worker_id=None,
                        article_id=article.id,
                        action="skipped_missing_worker_id",
                        reason="Timed-out article has no worker id",
                    )
                )
                continue

            article.status = ArticleStatus.queued
            article.current_step = None
            article.celery_task_id = None
            note = payload.review_note or article.review_note

            generate_article.delay(
                article_id=str(article.id),
                job_id=str(article.job_id),
                topic=article.topic,
                keyword=article.keyword,
                review_note=note,
            )

            requeued_count += 1
            results.append(
                ReworkerResultItem(
                    worker_id=worker_id,
                    article_id=article.id,
                    action="requeued",
                )
            )

        if requeued_count > 0:
            job.failed = max(0, job.failed - requeued_count)
            job.status = JobStatus.running

        await db.commit()

        return ReworkerResponse(
            job_id=job_id,
            requested=len(timed_out_articles),
            requeued=requeued_count,
            skipped=len(timed_out_articles) - requeued_count,
            results=results,
        )
    except ProgrammingError as exc:
        _raise_if_schema_missing(exc)


@router.post("/{job_id}/reworker/by-worker-ids", response_model=ReworkerResponse)
async def reworker_by_ids(
    job_id: uuid.UUID,
    body: ReworkerRequest,
    db: AsyncSession = Depends(get_db),
) -> ReworkerResponse:
    """
    Requeue timed-out articles by explicit worker IDs (celery_task_id).
    This endpoint does not scan all timed-out items; it only handles IDs provided by the caller.
    """
    try:
        job_result = await db.execute(select(Job).where(Job.id == job_id))
        job = job_result.scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        requested_ids = list(dict.fromkeys(body.worker_ids))

        article_result = await db.execute(
            select(Article).where(
                Article.job_id == job_id,
                Article.celery_task_id.in_(requested_ids),
            )
        )
        articles = article_result.scalars().all()
        article_by_worker_id = {
            str(article.celery_task_id): article
            for article in articles
            if article.celery_task_id is not None
        }

        results: list[ReworkerResultItem] = []
        requeued_count = 0

        for worker_id in requested_ids:
            article = article_by_worker_id.get(worker_id)
            if article is None:
                results.append(
                    ReworkerResultItem(
                        worker_id=worker_id,
                        action="skipped_not_found",
                        reason="No article in this job matches the provided worker id",
                    )
                )
                continue

            is_timeout = (
                article.status == ArticleStatus.rejected
                and bool(article.review_note)
                and article.review_note.startswith(_TIMEOUT_NOTE_PREFIX)
            )
            if not is_timeout:
                results.append(
                    ReworkerResultItem(
                        worker_id=worker_id,
                        article_id=article.id,
                        action="skipped_not_timeout",
                        reason="Article is not in timeout state",
                    )
                )
                continue

            article.status = ArticleStatus.queued
            article.current_step = None
            note = body.review_note or article.review_note

            generate_article.delay(
                article_id=str(article.id),
                job_id=str(article.job_id),
                topic=article.topic,
                keyword=article.keyword,
                review_note=note,
            )

            requeued_count += 1
            results.append(
                ReworkerResultItem(
                    worker_id=worker_id,
                    article_id=article.id,
                    action="requeued",
                )
            )

        if requeued_count > 0:
            job.failed = max(0, job.failed - requeued_count)
            job.status = JobStatus.running

        await db.commit()

        return ReworkerResponse(
            job_id=job_id,
            requested=len(requested_ids),
            requeued=requeued_count,
            skipped=len(requested_ids) - requeued_count,
            results=results,
        )
    except ProgrammingError as exc:
        _raise_if_schema_missing(exc)

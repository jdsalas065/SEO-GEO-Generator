"""Router: GET /articles and PATCH /articles/{id}/review."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models import Article, ArticleStatus, Job, JobStatus
from app.schemas import ArticleOut, ReviewRequest, RetryRequest
from app.tasks import generate_article

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=list[ArticleOut])
async def list_articles(
    status: Optional[ArticleStatus] = Query(None, description="Filter by status"),
    job_id: Optional[uuid.UUID] = Query(None, description="Filter by job"),
    db: AsyncSession = Depends(get_db),
) -> list[ArticleOut]:
    """List articles, optionally filtered by status and/or job_id."""
    stmt = select(Article)
    if status is not None:
        stmt = stmt.where(Article.status == status)
    if job_id is not None:
        stmt = stmt.where(Article.job_id == job_id)
    stmt = stmt.order_by(Article.created_at.desc())

    result = await db.execute(stmt)
    articles = result.scalars().all()
    return [ArticleOut.model_validate(a) for a in articles]


@router.patch("/{article_id}/review", response_model=ArticleOut)
async def review_article(
    article_id: uuid.UUID,
    body: ReviewRequest,
    db: AsyncSession = Depends(get_db),
) -> ArticleOut:
    """
    Approve or reject an article.
    - approve → status = approved
    - reject  → status = rejected + re-queue Celery task with review_note
    """
    result = await db.execute(select(Article).where(Article.id == article_id))
    article = result.scalar_one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    if article.status != ArticleStatus.pending_review:
        raise HTTPException(
            status_code=400,
            detail=f"Article is not pending review (current status: {article.status})",
        )

    if body.action == "approve":
        article.status = ArticleStatus.approved

    elif body.action == "reject":
        if not body.note:
            raise HTTPException(
                status_code=422, detail="A review note is required when rejecting"
            )
        article.review_note = body.note
        article.status = ArticleStatus.queued

        # Re-queue with the review note appended to the prompt
        generate_article.delay(
            article_id=str(article.id),
            job_id=str(article.job_id),
            topic=article.topic,
            keyword=article.keyword,
            review_note=body.note,
        )

    await db.commit()
    await db.refresh(article)
    return ArticleOut.model_validate(article)


@router.post("/{article_id}/retry", response_model=ArticleOut)
async def retry_article(
    article_id: uuid.UUID,
    body: RetryRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> ArticleOut:
    """
    Retry a rejected article by re-queueing the generation task.
    """
    payload = body or RetryRequest()

    article_result = await db.execute(select(Article).where(Article.id == article_id))
    article = article_result.scalar_one_or_none()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    if article.status != ArticleStatus.rejected:
        raise HTTPException(
            status_code=400,
            detail=f"Article is not rejected (current status: {article.status})",
        )

    job_result = await db.execute(select(Job).where(Job.id == article.job_id))
    job = job_result.scalar_one_or_none()

    article.status = ArticleStatus.queued
    article.current_step = None
    article.celery_task_id = None
    if payload.note:
        article.review_note = payload.note

    if job is not None:
        job.failed = max(0, job.failed - 1)
        job.status = JobStatus.running

    generate_article.delay(
        article_id=str(article.id),
        job_id=str(article.job_id),
        topic=article.topic,
        keyword=article.keyword,
        review_note=payload.note or article.review_note,
    )

    await db.commit()
    await db.refresh(article)
    return ArticleOut.model_validate(article)

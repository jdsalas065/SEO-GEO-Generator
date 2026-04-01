"""Celery tasks for article generation."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from celery import Celery

from app.llm_client import call_llm
from app.post_processor import count_words, save_markdown, validate_content
from app.prompt_builder import build_prompt

logger = logging.getLogger(__name__)

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

celery_app = Celery(
    "seo_geo",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    worker_prefetch_multiplier=1,
)

ARTICLES_DIR = Path(os.environ.get("ARTICLES_DIR", "articles"))


def _run_async(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine from a synchronous Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _update_article_status(article_id: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """Async helper to update article fields in the database."""
    from sqlalchemy import update

    from app.database import get_session_factory as _get_sf
    from app.models import Article

    async with _get_sf()() as session:
        stmt = update(Article).where(Article.id == uuid.UUID(article_id)).values(**kwargs)
        await session.execute(stmt)
        await session.commit()


async def _increment_job_counter(job_id: str, field: str) -> None:
    """Async helper to increment a job counter (done or failed)."""
    from sqlalchemy import select, update

    from app.database import get_session_factory as _get_sf
    from app.models import Job, JobStatus

    async with _get_sf()() as session:
        result = await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
        job = result.scalar_one_or_none()
        if job is None:
            return

        kwargs = {field: getattr(job, field) + 1}
        # Check if job is now fully complete
        new_done = job.done + (1 if field == "done" else 0)
        new_failed = job.failed + (1 if field == "failed" else 0)
        if (new_done + new_failed) >= job.total:
            kwargs["status"] = JobStatus.done

        stmt = update(Job).where(Job.id == uuid.UUID(job_id)).values(**kwargs)
        await session.execute(stmt)
        await session.commit()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)  # type: ignore[misc]
def generate_article(
    self,  # noqa: ANN001
    article_id: str,
    job_id: str,
    topic: str,
    keyword: str | None = None,
    review_note: str | None = None,
) -> dict:
    """
    Main Celery task:
    1. Build prompt
    2. Call LLM
    3. Validate content
    4. Save as Markdown
    5. Update database
    """
    from app.models import ArticleStatus

    try:
        # Mark as generating
        _run_async(
            _update_article_status(
                article_id,
                status=ArticleStatus.generating,
                celery_task_id=self.request.id,
            )
        )

        # Build and send prompt
        prompt = build_prompt(topic=topic, keyword=keyword, review_note=review_note)
        content = call_llm(prompt)

        # Validate
        errors = validate_content(content)
        if errors:
            error_summary = "; ".join(errors)
            logger.warning("Article %s validation errors: %s", article_id, error_summary)
            _run_async(
                _update_article_status(
                    article_id,
                    status=ArticleStatus.rejected,
                    review_note=f"Auto-validation failed: {error_summary}",
                )
            )
            _run_async(_increment_job_counter(job_id, "failed"))
            return {"status": "rejected", "errors": errors}

        # Save to disk
        wc = count_words(content)
        md_path = ARTICLES_DIR / job_id / f"{article_id}.md"
        save_markdown(content, md_path)

        # Update DB → pending_review
        _run_async(
            _update_article_status(
                article_id,
                status=ArticleStatus.pending_review,
                content=content,
                word_count=wc,
            )
        )
        _run_async(_increment_job_counter(job_id, "done"))

        return {"status": "pending_review", "word_count": wc}

    except Exception as exc:
        logger.exception("Task failed for article %s: %s", article_id, exc)
        try:
            from app.models import ArticleStatus

            _run_async(
                _update_article_status(
                    article_id,
                    status=ArticleStatus.rejected,
                    review_note=f"Task error: {exc}",
                )
            )
            _run_async(_increment_job_counter(job_id, "failed"))
        except Exception:
            pass
        raise self.retry(exc=exc)

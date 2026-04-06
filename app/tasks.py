"""Celery tasks for article generation."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded, TimeLimitExceeded
from celery.signals import worker_process_init, worker_process_shutdown

from app.llm_client import call_llm, LLMClient, LLMJsonParseError
from app.image_search import attach_images
from app.post_processor import (
    count_words,
    save_markdown,
    validate_content,
    extract_meta_description,
    calculate_seo_score,
    build_markdown_with_frontmatter,
)
from app.prompt_builder import (
    build_prompt,
    build_outline_prompt,
    build_fallback_outline,
    build_write_prompt,
    build_seo_check_prompt,
    load_rules as load_prompt_rules,
)

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
TASK_SOFT_TIME_LIMIT_SECONDS = int(os.environ.get("TASK_SOFT_TIME_LIMIT_SECONDS", "900"))
TASK_HARD_TIME_LIMIT_SECONDS = int(
    os.environ.get("TASK_HARD_TIME_LIMIT_SECONDS", str(TASK_SOFT_TIME_LIMIT_SECONDS + 30))
)
TIMEOUT_REVIEW_NOTE_PREFIX = "Task timeout after"

_worker_loop: asyncio.AbstractEventLoop | None = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return a stable event loop for this worker process."""
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


@worker_process_init.connect
def _on_worker_process_init(**kwargs) -> None:  # type: ignore[no-untyped-def]
    """Reset per-process async state after worker fork/start."""
    del kwargs
    global _worker_loop
    _worker_loop = None
    from app.database import reset_engine_and_session_factory

    reset_engine_and_session_factory()


@worker_process_shutdown.connect
def _on_worker_process_shutdown(**kwargs) -> None:  # type: ignore[no-untyped-def]
    """Close the process loop to avoid leaking resources on shutdown."""
    del kwargs
    global _worker_loop
    if _worker_loop is not None and not _worker_loop.is_closed():
        _worker_loop.close()
    _worker_loop = None


def _run_async(coro):  # type: ignore[no-untyped-def]
    """Run an async coroutine from a synchronous Celery task."""
    return _get_worker_loop().run_until_complete(coro)


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


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=TASK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=TASK_HARD_TIME_LIMIT_SECONDS,
)  # type: ignore[misc]
def generate_article(
    self,  # noqa: ANN001
    article_id: str,
    job_id: str,
    topic: str,
    keyword: str | None = None,
    review_note: str | None = None,
) -> dict:
    """
    Multi-step LLM pipeline for article generation:
    1. Step 1 (outline): Generate structure/outline
    2. Step 2 (write): Write article using outline
    3. Step 3 (seo_check): Validate and score SEO
    4. Post-process: Build markdown with frontmatter
    5. Save to database
    
    If any step fails, entire task retries from step 1.
    """
    from app.models import ArticleStatus

    try:
        config = load_prompt_rules()
        llm_config = config.get("llm", {})
        steps_config = llm_config.get("steps", {})
        
        # Mark as generating
        _run_async(
            _update_article_status(
                article_id,
                status=ArticleStatus.generating,
                celery_task_id=self.request.id,
            )
        )

        # =====================================================================
        # STEP 1: Generate Outline
        # =====================================================================
        logger.info("Article %s: Starting step 1 (outline)", article_id)
        _run_async(
            _update_article_status(article_id, current_step="outline")
        )
        
        outline_cfg = steps_config.get("outline", {})
        outline_client = LLMClient.from_step_config(outline_cfg)
        outline_prompt = build_outline_prompt(topic, config, review_note or "")
        
        try:
            outline = outline_client.generate_json(outline_prompt, max_retries=2)
        except LLMJsonParseError as e:
            logger.warning(
                "Article %s: Outline JSON parse failed (%s). Falling back to deterministic outline.",
                article_id,
                e,
            )
            outline = build_fallback_outline(topic, config)

        logger.info("Article %s: Step 1 (outline) completed", article_id)

        # =====================================================================
        # STEP 2: Write Article
        # =====================================================================
        logger.info("Article %s: Starting step 2 (write)", article_id)
        _run_async(
            _update_article_status(article_id, current_step="writing")
        )
        
        write_cfg = steps_config.get("write", {})
        write_client = LLMClient.from_step_config(write_cfg)
        write_prompt = build_write_prompt(topic, outline, config)
        
        article_md = write_client.generate(write_prompt)
        
        # Validate article content
        errors = validate_content(article_md)
        if errors:
            error_summary = "; ".join(errors)
            logger.warning("Article %s: Validation errors: %s", article_id, error_summary)
            _run_async(
                _update_article_status(
                    article_id,
                    status=ArticleStatus.rejected,
                    review_note=f"Content validation failed: {error_summary}",
                    current_step=None,
                )
            )
            _run_async(_increment_job_counter(job_id, "failed"))
            return {"status": "rejected", "errors": errors}

        logger.info("Article %s: Step 2 (write) completed", article_id)

        # =====================================================================
        # STEP 3: SEO Check
        # =====================================================================
        logger.info("Article %s: Starting step 3 (seo_check)", article_id)
        _run_async(
            _update_article_status(article_id, current_step="seo_check")
        )
        
        seo_cfg = steps_config.get("seo_check", {})
        seo_client = LLMClient.from_step_config(seo_cfg)
        seo_prompt = build_seo_check_prompt(topic, article_md, config)
        
        try:
            seo_result = seo_client.generate_json(seo_prompt)
        except LLMJsonParseError as e:
            logger.error("Article %s: SEO check JSON parse failed: %s", article_id, e)
            # Don't reject - use defaults and continue
            seo_result = {
                "meta_description": f"Vietnamese content about {topic[:60]}",
                "issues": ["SEO check unavailable"],
                "geo_score": 0.0,
            }

        logger.info("Article %s: Step 3 (seo_check) completed", article_id)

        # =====================================================================
        # POST-PROCESS: Extract meta and build markdown with frontmatter
        # =====================================================================
        meta_description = seo_result.get("meta_description", "")
        if not meta_description:
            meta_description = f"Vietnamese content about {topic[:60]}"
        
        # Clean up meta description to be within limits
        meta_description = meta_description[:160].strip()
        
        geo_score = seo_result.get("geo_score", 0.0)
        # Extract from meta description tag if present, otherwise use current content
        meta_description_from_content, clean_content = extract_meta_description(article_md)
        if meta_description_from_content:
            meta_description = meta_description_from_content
        
        # Calculate additional metrics
        wc = count_words(clean_content)
        
        # Build markdown with frontmatter
        llm_provider = str(write_cfg.get("provider", llm_config.get("provider", "anthropic"))).lower()
        md_content = build_markdown_with_frontmatter(
            topic=topic,
            content=clean_content,
            meta_description=meta_description,
            seo_score=geo_score,
            word_count=wc,
            llm_provider=llm_provider,
        )

        # Auto-attach images to selected H2 sections without failing the article pipeline.
        md_content, images_json = attach_images(
            md_content=md_content,
            topic=topic,
            keyword=keyword,
            article_id=article_id,
        )

        # Save to disk
        md_path = ARTICLES_DIR / job_id / f"{article_id}.md"
        save_markdown(md_content, md_path)

        # Update DB → pending_review
        _run_async(
            _update_article_status(
                article_id,
                status=ArticleStatus.pending_review,
                content=clean_content,
                md_content=md_content,
                images_json=images_json,
                word_count=wc,
                seo_score=geo_score,
                current_step=None,
            )
        )
        _run_async(_increment_job_counter(job_id, "done"))

        logger.info("Article %s: Complete (word_count=%d, seo_score=%.2f)", 
                   article_id, wc, geo_score)
        
        return {
            "status": "pending_review",
            "word_count": wc,
            "seo_score": geo_score,
            "outline_sections": len(outline.get("sections", [])),
        }

    except (SoftTimeLimitExceeded, TimeLimitExceeded) as exc:
        logger.error(
            "Article %s: timeout after soft=%ss/hard=%ss",
            article_id,
            TASK_SOFT_TIME_LIMIT_SECONDS,
            TASK_HARD_TIME_LIMIT_SECONDS,
        )
        try:
            from app.models import ArticleStatus

            _run_async(
                _update_article_status(
                    article_id,
                    status=ArticleStatus.rejected,
                    review_note=f"{TIMEOUT_REVIEW_NOTE_PREFIX} {TASK_SOFT_TIME_LIMIT_SECONDS}s (soft limit reached)",
                    current_step=None,
                )
            )
            _run_async(_increment_job_counter(job_id, "failed"))
        except Exception:
            pass
        return {
            "status": "timeout",
            "error": "task_timeout",
            "soft_time_limit_seconds": TASK_SOFT_TIME_LIMIT_SECONDS,
        }

    except Exception as exc:
        logger.exception("Article %s: Task failed: %s", article_id, exc)
        try:
            from app.models import ArticleStatus

            # Reset current_step on error
            _run_async(
                _update_article_status(
                    article_id,
                    status=ArticleStatus.rejected,
                    review_note=f"Task error: {exc}",
                    current_step=None,
                )
            )
            _run_async(_increment_job_counter(job_id, "failed"))
        except Exception:
            pass
        raise self.retry(exc=exc)

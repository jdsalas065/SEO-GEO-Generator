"""Router: POST /jobs and GET /jobs/{id}."""
from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles
import aiofiles.os
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.input_parser import parse_input
from app.models import Article, ArticleStatus, Job, JobStatus
from app.schemas import JobOut
from app.tasks import generate_article

router = APIRouter(prefix="/jobs", tags=["jobs"])

_UPLOAD_DIR = Path("uploads")


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> JobOut:
    """
    Upload an Excel (.xlsx) or JSON file containing article topics.
    Creates a batch job and queues Celery tasks for each topic.
    """
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


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> JobOut:
    """Return progress info for a batch job."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobOut.model_validate(job)

"""Router: GET /export — download ZIP of approved .md files."""
from __future__ import annotations

import io
import uuid
import zipfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from slugify import slugify
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models import Article, ArticleStatus

router = APIRouter(prefix="/export", tags=["export"])


@router.get("")
async def export_articles(
    job_id: Optional[uuid.UUID] = Query(None, description="Filter by job"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Stream a ZIP archive of all approved articles as .md files.
    Optionally filter by job_id.
    
    File naming: slugified topic (up to 80 chars) + .md
    """
    stmt = select(Article).where(Article.status == ArticleStatus.approved)
    if job_id is not None:
        stmt = stmt.where(Article.job_id == job_id)

    result = await db.execute(stmt)
    articles = result.scalars().all()

    if not articles:
        raise HTTPException(status_code=404, detail="No approved articles found")

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for article in articles:
            # Use md_content if available (with frontmatter), fall back to content
            content = article.md_content or article.content or ""
            
            # Slugify topic: Vietnamese → ASCII, max 80 chars, add .md extension
            topic_slug = slugify(article.topic, allow_unicode=False)[:80]
            filename = f"{topic_slug}.md"
            
            zf.writestr(filename, content.encode("utf-8"))

    buf.seek(0)

    zip_filename = f"articles_{job_id}.zip" if job_id else "articles.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )

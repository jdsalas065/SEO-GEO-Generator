"""Router: GET /export — download self-contained ZIP bundles."""
from __future__ import annotations

import io
import mimetypes
import uuid
import zipfile
from typing import Optional
from html import escape
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import frontmatter
import httpx
import markdown as markdown_lib
from slugify import slugify
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models import Article

router = APIRouter(prefix="/export", tags=["export"])


def _exportable_content(article: Article) -> str:
    return article.md_content or article.content or ""


def _article_folder_name(article: Article, position: int | None, total: int) -> str:
    slug = slugify(article.topic, allow_unicode=False)[:80]
    base = slug or str(article.id)
    if total > 1 and position is not None:
        return f"{position:02d}-{base}"
    return base


def _image_extension(image_url: str, content_type: str | None) -> str:
    parsed_path = Path(urlparse(image_url).path)
    suffix = parsed_path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg"}:
        return suffix

    guessed = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    if guessed:
        return guessed

    return ".jpg"


async def _download_image_asset(image_url: str) -> tuple[bytes, str] | None:
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
        response = await client.get(image_url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        return response.content, content_type


def _rewrite_image_sources(text: str, source_url: str, local_path: str) -> str:
    escaped_source = escape(source_url, quote=True)
    escaped_local = escape(local_path, quote=True)
    text = text.replace(f'src="{escaped_source}"', f'src="{escaped_local}"')
    text = text.replace(f"src='{escaped_source}'", f"src='{escaped_local}'")
    return text


def _render_html(article: Article, md_content: str, local_image_paths: dict[str, str]) -> str:
    post = frontmatter.loads(md_content)
    title = str(post.metadata.get("title") or article.topic or article.id)
    meta_description = str(post.metadata.get("meta_description") or "")

    body_html = markdown_lib.markdown(
        post.content,
        extensions=["extra", "tables", "sane_lists"],
        output_format="html5",
    )

    for source_url, local_path in local_image_paths.items():
        body_html = _rewrite_image_sources(body_html, source_url, local_path)

    meta_description_tag = (
        f'<meta name="description" content="{escape(meta_description, quote=True)}">'
        if meta_description
        else ""
    )

    return (
        "<!doctype html>\n"
        '<html lang="vi">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{escape(title)}</title>\n"
        f"  {meta_description_tag}\n"
        "  <style>\n"
        "    body { font-family: Arial, sans-serif; line-height: 1.7; margin: 0; background: #f7f7f4; color: #1f2937; }\n"
        "    main { max-width: 920px; margin: 0 auto; padding: 32px 20px 56px; background: #fff; min-height: 100vh; box-shadow: 0 8px 40px rgba(15, 23, 42, 0.06); }\n"
        "    img { max-width: 100%; height: auto; }\n"
        "    figure { margin: 1.5rem 0; }\n"
        "    figcaption { font-size: 0.95rem; color: #6b7280; margin-top: 0.5rem; }\n"
        "    pre { overflow-x: auto; padding: 1rem; background: #0f172a; color: #e5e7eb; border-radius: 0.75rem; }\n"
        "    code { font-family: Consolas, Monaco, monospace; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        "  <main>\n"
        f"{body_html}\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


async def _write_article_bundle(
    zf: zipfile.ZipFile,
    article: Article,
    folder_name: str,
) -> None:
    md_content = _exportable_content(article)
    if not md_content.strip():
        raise HTTPException(status_code=404, detail=f"Article {article.id} has no exportable content")

    images_json = article.images_json or []
    local_image_paths: dict[str, str] = {}
    localized_md_content = md_content

    zf.writestr(f"{folder_name}/images/", b"")

    for index, image in enumerate(images_json, start=1):
        image_url = image.get("image_url")
        if not isinstance(image_url, str) or not image_url:
            continue

        downloaded = await _download_image_asset(image_url)
        if downloaded is None:
            continue

        image_bytes, content_type = downloaded
        extension = _image_extension(image_url, content_type)
        filename = f"image-{index:02d}{extension}"
        local_path = f"images/{filename}"
        zf.writestr(f"{folder_name}/{local_path}", image_bytes)
        local_image_paths[image_url] = local_path
        localized_md_content = _rewrite_image_sources(localized_md_content, image_url, local_path)

    zf.writestr(f"{folder_name}/article.md", localized_md_content.encode("utf-8"))

    html_content = _render_html(article, localized_md_content, local_image_paths)
    zf.writestr(f"{folder_name}/index.html", html_content.encode("utf-8"))


@router.get("")
async def export_articles(
    article_id: Optional[uuid.UUID] = Query(None, description="Export a single article"),
    job_id: Optional[uuid.UUID] = Query(None, description="Filter by job"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """
    Stream a ZIP archive for one article or a whole job.

    - article_id: export a single article as a folder bundle
    - job_id: export all generated articles in the job as folder bundles
    - approval status is not required
    """
    if article_id is not None and job_id is not None:
        raise HTTPException(status_code=400, detail="Provide only one of article_id or job_id")

    if article_id is None and job_id is None:
        raise HTTPException(status_code=400, detail="article_id or job_id is required")

    if article_id is not None:
        result = await db.execute(select(Article).where(Article.id == article_id))
        article = result.scalar_one_or_none()
        if article is None:
            raise HTTPException(status_code=404, detail="Article not found")
        articles = [article]
    else:
        result = await db.execute(select(Article).where(Article.job_id == job_id))
        articles = result.scalars().all()

    exportable_articles = [article for article in articles if _exportable_content(article).strip()]
    if not exportable_articles:
        raise HTTPException(status_code=404, detail="No exportable articles found")

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        total = len(exportable_articles)
        for position, article in enumerate(exportable_articles, start=1):
            folder_name = _article_folder_name(article, position, total)
            await _write_article_bundle(zf, article, folder_name)

    buf.seek(0)

    if article_id is not None:
        zip_filename = f"article_{article_id}.zip"
    elif job_id is not None:
        zip_filename = f"job_{job_id}.zip"
    else:
        zip_filename = "articles.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )

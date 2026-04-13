"""Integration tests for API endpoints (using SQLite in-memory DB)."""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path

import openpyxl
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.future import select

from app.models import Article, ArticleStatus, Job, JobStatus
from app.post_processor import build_markdown_with_frontmatter


def make_json_bytes(topics: list) -> bytes:
    return json.dumps(topics).encode()


def make_xlsx_bytes(rows: list[dict]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    if rows:
        headers = list(rows[0].keys())
        ws.append(headers)
        for row in rows:
            ws.append([row.get(h) for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_job_json(client: AsyncClient, mocker):
    delay_mock = mocker.patch("app.routers.jobs.generate_article.delay")
    payload = [{"topic": "Ẩm thực Việt Nam", "keyword": "ẩm thực", "outline": {"H2": ["Giới thiệu"]}}]
    resp = await client.post(
        "/jobs",
        files={"file": ("topics.json", io.BytesIO(make_json_bytes(payload)), "application/json")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["total"] == 1
    assert data["status"] == "running"
    assert delay_mock.call_count == 1
    assert delay_mock.call_args.kwargs["keyword"] == "ẩm thực"
    assert delay_mock.call_args.kwargs["outline"] == {"H2": ["Giới thiệu"]}


@pytest.mark.asyncio
async def test_create_job_json_topic_only_still_works(client: AsyncClient, mocker):
    delay_mock = mocker.patch("app.routers.jobs.generate_article.delay")
    payload = [{"topic": "Chỉ có tiêu đề bài viết"}]
    resp = await client.post(
        "/jobs",
        files={"file": ("topics.json", io.BytesIO(make_json_bytes(payload)), "application/json")},
    )
    assert resp.status_code == 201
    assert delay_mock.call_count == 1
    assert delay_mock.call_args.kwargs["keyword"] is None
    assert delay_mock.call_args.kwargs["outline"] is None


@pytest.mark.asyncio
async def test_create_job_xlsx(client: AsyncClient, mocker):
    delay_mock = mocker.patch("app.routers.jobs.generate_article.delay")
    rows = [
        {"topic": "Du lịch Đà Nẵng", "keyword": "du lịch", "outline": json.dumps({"H2": ["Giới thiệu"]}, ensure_ascii=False)},
        {"topic": "Học lập trình Python"},
    ]
    xlsx_bytes = make_xlsx_bytes(rows)
    resp = await client.post(
        "/jobs",
        files={
            "file": (
                "topics.xlsx",
                io.BytesIO(xlsx_bytes),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["total"] == 2
    assert delay_mock.call_count == 2


@pytest.mark.asyncio
async def test_create_job_bad_format(client: AsyncClient):
    resp = await client.post(
        "/jobs",
        files={"file": ("topics.csv", io.BytesIO(b"topic\nTest"), "text/csv")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_job_empty_file(client: AsyncClient):
    resp = await client.post(
        "/jobs",
        files={"file": ("topics.json", io.BytesIO(b"[]"), "application/json")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_job_not_found(client: AsyncClient):
    resp = await client.get(f"/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_job(client: AsyncClient, mocker, db_session):
    mocker.patch("app.routers.jobs.generate_article.delay")
    payload = [{"topic": "Test topic", "outline": {"H2": ["Intro"]}}]
    resp = await client.post(
        "/jobs",
        files={"file": ("t.json", io.BytesIO(make_json_bytes(payload)), "application/json")},
    )
    job_id = resp.json()["id"]

    article = (
        await db_session.execute(select(Article).where(Article.job_id == uuid.UUID(job_id)))
    ).scalars().first()
    assert article is not None
    assert article.outline == {"H2": ["Intro"]}

    resp2 = await client.get(f"/jobs/{job_id}")
    assert resp2.status_code == 200
    assert resp2.json()["id"] == job_id


@pytest.mark.asyncio
async def test_get_jobs(client: AsyncClient, mocker):
    mocker.patch("app.routers.jobs.generate_article.delay")

    payload_1 = [{"topic": "Job one"}]
    payload_2 = [{"topic": "Job two"}]

    await client.post(
        "/jobs",
        files={"file": ("j1.json", io.BytesIO(make_json_bytes(payload_1)), "application/json")},
    )
    await client.post(
        "/jobs",
        files={"file": ("j2.json", io.BytesIO(make_json_bytes(payload_2)), "application/json")},
    )

    resp = await client.get("/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 2
    assert "timeout_count" in data[0]
    assert "percent" in data[0]


@pytest.mark.asyncio
async def test_get_jobs_includes_timeout_count(client: AsyncClient, db_session):
    job = Job(source_filename="timeouts.json", status=JobStatus.running, total=2, done=0, failed=1)
    db_session.add(job)
    await db_session.flush()

    timed_out_article = Article(
        job_id=job.id,
        topic="Slow article",
        status=ArticleStatus.rejected,
        review_note="Task timeout after 900s (soft limit reached)",
    )
    normal_failed_article = Article(
        job_id=job.id,
        topic="Validation failed",
        status=ArticleStatus.rejected,
        review_note="Content validation failed",
    )
    db_session.add_all([timed_out_article, normal_failed_article])
    await db_session.commit()

    resp = await client.get("/jobs")
    assert resp.status_code == 200
    data = resp.json()
    target = next(item for item in data if item["id"] == str(job.id))

    assert target["timeout_count"] == 1
    assert target["percent"] == 50


@pytest.mark.asyncio
async def test_reworker_by_worker_ids(client: AsyncClient, mocker, db_session):
    delay_mock = mocker.patch("app.routers.jobs.generate_article.delay")

    job = Job(source_filename="timeouts.json", status=JobStatus.failed, total=2, done=0, failed=2)
    db_session.add(job)
    await db_session.flush()

    timeout_article = Article(
        job_id=job.id,
        topic="Timeout topic",
        keyword="kw",
        status=ArticleStatus.rejected,
        review_note="Task timeout after 900s (soft limit reached)",
        celery_task_id="worker-timeout-1",
    )
    non_timeout_article = Article(
        job_id=job.id,
        topic="Other rejected",
        status=ArticleStatus.rejected,
        review_note="Content validation failed",
        celery_task_id="worker-not-timeout",
    )
    db_session.add_all([timeout_article, non_timeout_article])
    await db_session.commit()

    resp = await client.post(
        f"/jobs/{job.id}/reworker/by-worker-ids",
        json={
            "worker_ids": ["worker-timeout-1", "worker-not-timeout", "worker-missing"],
            "review_note": "Retry after timeout",
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["requested"] == 3
    assert data["requeued"] == 1
    assert data["skipped"] == 2

    actions = {item["worker_id"]: item["action"] for item in data["results"]}
    assert actions["worker-timeout-1"] == "requeued"
    assert actions["worker-not-timeout"] == "skipped_not_timeout"
    assert actions["worker-missing"] == "skipped_not_found"

    assert delay_mock.call_count == 1

    await db_session.refresh(timeout_article)
    await db_session.refresh(job)
    assert timeout_article.status == ArticleStatus.queued
    assert job.failed == 1
    assert job.status == JobStatus.running


@pytest.mark.asyncio
async def test_reworker_by_job_id(client: AsyncClient, mocker, db_session):
    delay_mock = mocker.patch("app.routers.jobs.generate_article.delay")

    job = Job(source_filename="timeouts.json", status=JobStatus.failed, total=3, done=0, failed=2)
    db_session.add(job)
    await db_session.flush()

    timeout_article_1 = Article(
        job_id=job.id,
        topic="Timeout topic 1",
        status=ArticleStatus.rejected,
        review_note="Task timeout after 900s (soft limit reached)",
        celery_task_id="worker-timeout-1",
    )
    timeout_article_2 = Article(
        job_id=job.id,
        topic="Timeout topic 2",
        status=ArticleStatus.rejected,
        review_note="Task timeout after 900s (soft limit reached)",
        celery_task_id="worker-timeout-2",
    )
    non_timeout_article = Article(
        job_id=job.id,
        topic="Normal reject",
        status=ArticleStatus.rejected,
        review_note="Content validation failed",
        celery_task_id="worker-not-timeout",
    )
    db_session.add_all([timeout_article_1, timeout_article_2, non_timeout_article])
    await db_session.commit()

    resp = await client.post(
        f"/jobs/{job.id}/reworker",
        json={"review_note": "Retry timed-out only", "limit": 1},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["requested"] == 1
    assert data["requeued"] == 1
    assert data["skipped"] == 0
    assert delay_mock.call_count == 1

    await db_session.refresh(timeout_article_1)
    await db_session.refresh(timeout_article_2)
    await db_session.refresh(non_timeout_article)
    await db_session.refresh(job)

    requeued_statuses = [timeout_article_1.status, timeout_article_2.status]
    assert requeued_statuses.count(ArticleStatus.queued) == 1
    assert requeued_statuses.count(ArticleStatus.rejected) == 1
    assert non_timeout_article.status == ArticleStatus.rejected
    assert job.failed == 1
    assert job.status == JobStatus.running


# ---------------------------------------------------------------------------
# Articles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_articles_empty(client: AsyncClient):
    resp = await client.get("/articles")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_articles_filtered_by_status(client: AsyncClient, mocker, db_session):
    mocker.patch("app.routers.jobs.generate_article.delay")
    payload = [{"topic": "Status filter test"}]
    await client.post(
        "/jobs",
        files={"file": ("t.json", io.BytesIO(make_json_bytes(payload)), "application/json")},
    )
    resp = await client.get("/articles?status=queued")
    assert resp.status_code == 200
    for article in resp.json():
        assert article["status"] == "queued"


@pytest.mark.asyncio
async def test_download_article_markdown(client: AsyncClient, db_session):
    job = Job(source_filename="download.json", status=JobStatus.done, total=1, done=1, failed=0)
    db_session.add(job)
    await db_session.flush()

    article = Article(
        job_id=job.id,
        topic="Bai viet tai xuong",
        status=ArticleStatus.approved,
        content="# Tieu de\n\nNoi dung bai viet.",
    )
    db_session.add(article)
    await db_session.commit()

    resp = await client.get(f"/articles/{article.id}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment;" in resp.headers["content-disposition"]
    assert "bai-viet-tai-xuong.md" in resp.headers["content-disposition"]
    assert "# Tieu de" in resp.text


@pytest.mark.asyncio
async def test_download_article_markdown_prefers_md_content_by_default(client: AsyncClient, db_session):
    job = Job(source_filename="download-md.json", status=JobStatus.done, total=1, done=1, failed=0)
    db_session.add(job)
    await db_session.flush()

    article = Article(
        job_id=job.id,
        topic="Bai viet co anh",
        status=ArticleStatus.approved,
        content="# Plain content",
        md_content="# Markdown content\n\n<figure><img src=\"https://img.example.com/a.jpg\"></figure>",
    )
    db_session.add(article)
    await db_session.commit()

    resp = await client.get(f"/articles/{article.id}/download")
    assert resp.status_code == 200
    assert "Markdown content" in resp.text
    assert "<figure>" in resp.text

    resp_content = await client.get(f"/articles/{article.id}/download?source=content")
    assert resp_content.status_code == 200
    assert "Plain content" in resp_content.text


@pytest.mark.asyncio
async def test_download_article_markdown_empty_content(client: AsyncClient, db_session):
    job = Job(source_filename="download-empty.json", status=JobStatus.done, total=1, done=1, failed=0)
    db_session.add(job)
    await db_session.flush()

    article = Article(
        job_id=job.id,
        topic="No content",
        status=ArticleStatus.approved,
        content=None,
        md_content=None,
    )
    db_session.add(article)
    await db_session.commit()

    resp = await client.get(f"/articles/{article.id}/download")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Article content is empty"


@pytest.mark.asyncio
async def test_review_article_not_found(client: AsyncClient):
    resp = await client.patch(
        f"/articles/{uuid.uuid4()}/review",
        json={"action": "approve"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_review_article_approve(client: AsyncClient, mocker, db_session):
    """Manually create a pending_review article and approve it."""
    from app.models import Article, ArticleStatus, Job, JobStatus

    job = Job(source_filename="test.json", status=JobStatus.running, total=1)
    db_session.add(job)
    await db_session.flush()

    article = Article(
        job_id=job.id,
        topic="Review test",
        status=ArticleStatus.pending_review,
        content="# Title\n\nContent\n\n## Section\n\n## Section2\n\nkết luận",
        word_count=10,
    )
    db_session.add(article)
    await db_session.commit()

    resp = await client.patch(
        f"/articles/{article.id}/review",
        json={"action": "approve"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_review_article_reject(client: AsyncClient, mocker, db_session):
    mocker.patch("app.routers.articles.generate_article.delay")

    from app.models import Article, ArticleStatus, Job, JobStatus

    job = Job(source_filename="test.json", status=JobStatus.running, total=1)
    db_session.add(job)
    await db_session.flush()

    article = Article(
        job_id=job.id,
        topic="Reject test",
        status=ArticleStatus.pending_review,
        content="# Title\n\nContent",
        word_count=5,
    )
    db_session.add(article)
    await db_session.commit()

    resp = await client.patch(
        f"/articles/{article.id}/review",
        json={"action": "reject", "note": "Needs more detail"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["review_note"] == "Needs more detail"


@pytest.mark.asyncio
async def test_review_article_reject_without_note(client: AsyncClient, db_session):
    from app.models import Article, ArticleStatus, Job, JobStatus

    job = Job(source_filename="test.json", status=JobStatus.running, total=1)
    db_session.add(job)
    await db_session.flush()

    article = Article(
        job_id=job.id,
        topic="Reject without note",
        status=ArticleStatus.pending_review,
    )
    db_session.add(article)
    await db_session.commit()

    resp = await client.patch(
        f"/articles/{article.id}/review",
        json={"action": "reject"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_review_article_wrong_status(client: AsyncClient, db_session):
    from app.models import Article, ArticleStatus, Job, JobStatus

    job = Job(source_filename="test.json", status=JobStatus.running, total=1)
    db_session.add(job)
    await db_session.flush()

    article = Article(
        job_id=job.id,
        topic="Already approved",
        status=ArticleStatus.approved,
    )
    db_session.add(article)
    await db_session.commit()

    resp = await client.patch(
        f"/articles/{article.id}/review",
        json={"action": "approve"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_retry_article_rejected(client: AsyncClient, mocker, db_session):
    delay_mock = mocker.patch("app.routers.articles.generate_article.delay")

    from app.models import Article, ArticleStatus, Job, JobStatus

    job = Job(source_filename="retry.json", status=JobStatus.done, total=1, done=0, failed=1)
    db_session.add(job)
    await db_session.flush()

    article = Article(
        job_id=job.id,
        topic="Retry me",
        keyword="retry",
        status=ArticleStatus.rejected,
        review_note="Content validation failed",
        celery_task_id="old-worker-id",
    )
    db_session.add(article)
    await db_session.commit()

    resp = await client.post(
        f"/articles/{article.id}/retry",
        json={"note": "Please improve structure and examples"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    assert data["review_note"] == "Please improve structure and examples"

    await db_session.refresh(article)
    await db_session.refresh(job)
    assert article.status == ArticleStatus.queued
    assert article.celery_task_id is None
    assert job.failed == 0
    assert job.status == JobStatus.running

    delay_mock.assert_called_once()


@pytest.mark.asyncio
async def test_retry_article_not_found(client: AsyncClient):
    resp = await client.post(f"/articles/{uuid.uuid4()}/retry", json={})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_retry_article_wrong_status(client: AsyncClient, db_session):
    from app.models import Article, ArticleStatus, Job, JobStatus

    job = Job(source_filename="retry.json", status=JobStatus.running, total=1, done=0, failed=0)
    db_session.add(job)
    await db_session.flush()

    article = Article(
        job_id=job.id,
        topic="Already queued",
        status=ArticleStatus.queued,
    )
    db_session.add(article)
    await db_session.commit()

    resp = await client.post(f"/articles/{article.id}/retry", json={})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_no_articles(client: AsyncClient):
    resp = await client.get(f"/export?job_id={uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_article_id_returns_self_contained_bundle(client: AsyncClient, db_session, mocker):
    from slugify import slugify

    mocker.patch(
        "app.routers.export._download_image_asset",
        return_value=(b"fake-png-bytes", "image/png"),
    )

    job = Job(source_filename="test.json", status=JobStatus.done, total=1, done=1)
    db_session.add(job)
    await db_session.flush()

    article = Article(
        job_id=job.id,
        topic="Export test",
        status=ArticleStatus.pending_review,
        md_content=build_markdown_with_frontmatter(
            topic="Export test",
            content="# Export\n\nContent here.\n\n<figure>\n  <img src=\"https://example.com/test-image.png\" alt=\"Export test\" loading=\"lazy\">\n  <figcaption>Export test</figcaption>\n</figure>",
            meta_description="Export test description",
            seo_score=0.8,
            word_count=5,
            llm_provider="claude",
        ),
        images_json=[
            {
                "h2": "Export test",
                "query": "Export test",
                "image_url": "https://example.com/test-image.png",
                "alt": "Export test",
                "caption": "Export test",
                "rank": 3,
                "engine": "bing",
            }
        ],
    )
    db_session.add(article)
    await db_session.commit()

    resp = await client.get(f"/export?article_id={article.id}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    # Verify ZIP contains the article with slugified topic name
    buf = io.BytesIO(resp.content)
    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
        folder = slugify(article.topic, allow_unicode=False)[:80]
        assert f"{folder}/article.md" in names
        assert f"{folder}/index.html" in names
        assert f"{folder}/images/" in names
        assert f"{folder}/images/image-01.png" in names

        md_content = zf.read(f"{folder}/article.md").decode("utf-8")
        assert "# Export" in md_content
        assert "images/image-01.png" in md_content
        assert "https://example.com/test-image.png" not in md_content

        html_content = zf.read(f"{folder}/index.html").decode("utf-8")
        assert f"images/image-01.png" in html_content
        assert "https://example.com/test-image.png" not in html_content


@pytest.mark.asyncio
async def test_export_job_id_returns_multiple_article_bundles(client: AsyncClient, db_session, mocker):
    mocker.patch(
        "app.routers.export._download_image_asset",
        return_value=(b"fake-png-bytes", "image/png"),
    )

    job = Job(source_filename="job.json", status=JobStatus.done, total=2, done=2)
    db_session.add(job)
    await db_session.flush()

    article1 = Article(
        job_id=job.id,
        topic="Alpha article",
        status=ArticleStatus.pending_review,
        content="# Alpha\n\nBody one.",
    )
    article2 = Article(
        job_id=job.id,
        topic="Beta article",
        status=ArticleStatus.queued,
        content="# Beta\n\nBody two.",
    )
    db_session.add_all([article1, article2])
    await db_session.commit()

    resp = await client.get(f"/export?job_id={job.id}")
    assert resp.status_code == 200

    buf = io.BytesIO(resp.content)
    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
        assert any(name.endswith("/article.md") for name in names)
        assert any(name.endswith("/index.html") for name in names)
        assert len([name for name in names if name.endswith("/article.md")]) == 2
        assert len([name for name in names if name.endswith("/index.html")]) == 2

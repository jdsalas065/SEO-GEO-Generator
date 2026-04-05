# GitHub Copilot — Apply Changes to Content Pipeline
# Mở Copilot Chat trong VS Code, paste toàn bộ nội dung này.

---

## Tổng quan repo hiện tại

Repo `content-pipeline`: FastAPI + Celery + Redis + PostgreSQL.
Nhận danh sách topics (Excel/JSON), sinh bài SEO/GEO tiếng Việt qua LLM,
human review rồi approve vào DB.

Cần apply 2 thay đổi sau. Làm lần lượt, hỏi confirm sau mỗi thay đổi.

---

## CHANGE 1 — Output bài viết là file `.md` (Markdown)

Bài viết SEO sau khi sinh và được approve phải được lưu và export
dưới dạng file `.md` thuần Markdown — không phải HTML, không phải plain text.

### Yêu cầu cụ thể

**Cấu trúc file .md bắt buộc:**

```markdown
---
title: "{topic}"
meta_description: "{150-160 ký tự}"
seo_score: {0.0-1.0}
word_count: {số}
generated_at: {ISO8601}
llm_provider: {claude|openai|gemini}
---

# {H1 tiêu đề bài}

{đoạn mở đầu 2-3 câu — trả lời thẳng câu hỏi, dùng làm GEO snippet}

## {H2 section 1}

### {H3 nếu có}

...

## FAQ

**{câu hỏi 1}**
{trả lời ngắn}

...
```

**Sửa `app/post_processor.py`:**
- Sau khi validate xong, đảm bảo `md_content` trong `PostProcessResult`
  đã có YAML frontmatter đầy đủ ở đầu file
- Tách meta description từ tag `<!-- meta: ... -->` trong bài,
  đưa vào frontmatter, rồi xoá tag đó khỏi body
- Đảm bảo cuối file có đúng 1 newline

**Sửa `app/routers/export.py`:**
- Tên file ZIP entry: `slugify(topic, allow_unicode=False)[:80] + ".md"`
- Thêm `python-slugify` vào `requirements.txt`
- Export chỉ articles có `status = "approved"`

**Sửa `app/models.py`:**
- Đảm bảo field `md_content` là `Text` (không phải VARCHAR có giới hạn)

**Test** (`tests/test_md_output.py`):
- Bài đầy đủ → frontmatter parse được bằng `python-frontmatter`
- Export ZIP → unzip ra file `.md`, đọc được frontmatter
- Tên file slug từ tiếng Việt có dấu → ASCII, không có ký tự đặc biệt

---

## CHANGE 2 — Multi-step LLM pipeline + Job status polling

### 2A — Tách pipeline thành 3 bước (tối ưu chất lượng + chi phí)

**Vấn đề hiện tại:** 1 prompt → 1 LLM call cho bài 1200–1800 từ.
Model bị lạc ở phần cuối bài, FAQ viết qua loa, khó kiểm soát cấu trúc.

**Giải pháp:** 3 bước, mỗi bước dùng model phù hợp:

```
Bước 1 — Outline   → model rẻ  (Haiku / gpt-4o-mini)
Bước 2 — Viết bài  → model tốt (Sonnet / gpt-4o)
Bước 3 — SEO audit → model rẻ  (Haiku / gpt-4o-mini)
```

**Sửa `config/rules.yaml`** — thêm section `llm.steps`:

```yaml
llm:
  steps:
    outline:
      provider: "claude"
      model: "claude-haiku-4-5-20251001"
      max_tokens: 800
      temperature: 0.3

    write:
      provider: "claude"
      model: "claude-sonnet-4-6"
      max_tokens: 4096
      temperature: 0.7

    seo_check:
      provider: "claude"
      model: "claude-haiku-4-5-20251001"
      max_tokens: 600
      temperature: 0.2
```

**Sửa `app/prompt_builder.py`** — tách thành 3 hàm:

```python
def build_outline_prompt(topic: str, config: dict, review_note: str = "") -> dict:
    """
    Yêu cầu LLM trả về JSON (không có markdown fence):
    {
      "h1": "...",
      "sections": [
        {"h2": "...", "h3s": ["..."], "key_points": ["..."]}
      ],
      "keywords": ["..."],
      "faq": [{"q": "...", "a": "..."}]  // đúng 5 câu
    }
    Nếu có review_note → thêm vào cuối system prompt:
    "Lần trước bị reject vì: {review_note}. Hãy cải thiện ở lần này."
    """

def build_write_prompt(topic: str, outline: dict, config: dict) -> dict:
    """
    Inject outline JSON vào system prompt.
    Yêu cầu: viết đúng thứ tự H1→H2→H3 từ outline,
    không bỏ section, không thêm section ngoài outline.
    Mở đầu bằng đoạn GEO snippet 2-3 câu.
    Kết thúc bằng FAQ section từ outline.
    """

def build_seo_check_prompt(topic: str, article_md: str, config: dict) -> dict:
    """
    Yêu cầu LLM trả về JSON:
    {
      "meta_description": "...",  // 150-160 ký tự tiếng Việt
      "issues": ["..."],          // vấn đề SEO nếu có, [] nếu không
      "geo_score": 0.0            // 0.0-1.0, tự đánh giá GEO readiness
    }
    """
```

**Sửa `app/llm_client.py`** — thêm:

```python
@classmethod
def from_step_config(cls, step_cfg: dict) -> "LLMClient":
    """Khởi tạo từ config của 1 bước cụ thể."""

def generate_json(self, prompt: dict) -> dict:
    """
    Gọi generate(), parse JSON response.
    Nếu parse fail → retry 1 lần với suffix "Trả về JSON thuần, không markdown."
    Nếu vẫn fail → raise LLMJsonParseError
    """
```

**Sửa `app/models.py`** — thêm field vào `Article`:

```python
current_step: Mapped[str | None]  # "outline" | "writing" | "seo_check" | None
```

Tạo Alembic migration: `alembic revision --autogenerate -m "add_current_step"`

**Sửa `app/tasks.py`** — task `generate_article` chạy 3 bước tuần tự:

```python
@celery.task(bind=True, max_retries=3)
def generate_article(self, topic, job_id, config_version, review_note=""):
    config = load_config()

    # Bước 1
    set_article_step(job_id, topic, "outline")
    outline = LLMClient.from_step_config(config["llm"]["steps"]["outline"]) \
                       .generate_json(build_outline_prompt(topic, config, review_note))

    # Bước 2
    set_article_step(job_id, topic, "writing")
    article_md = LLMClient.from_step_config(config["llm"]["steps"]["write"]) \
                          .generate(build_write_prompt(topic, outline, config))

    # Bước 3
    set_article_step(job_id, topic, "seo_check")
    seo = LLMClient.from_step_config(config["llm"]["steps"]["seo_check"]) \
                   .generate_json(build_seo_check_prompt(topic, article_md, config))

    # Post-process + lưu DB
    result = validate_and_score(article_md, config, seo)
    save_article(job_id, topic, result.md_content, result, config_version)
```

Nếu bất kỳ bước nào raise exception → `self.retry()` bắt đầu lại từ bước 1.

**Test** (`tests/test_pipeline_steps.py`):
- Mock 3 LLM calls riêng → verify đúng model được gọi ở đúng bước
- `generate_json` nhận response không phải JSON → retry → vẫn fail → raise
- Task retry → `current_step` reset về `"outline"`

---

### 2B — Job status: simple polling

**Giải pháp:** Client gọi `GET /jobs/{job_id}` mỗi 3–5 giây.
BE chỉ đọc DB, không cần WebSocket hay SSE.

**Sửa `app/routers/jobs.py`** — `GET /jobs/{job_id}` trả:

```json
{
  "job_id": "uuid",
  "batch_name": "...",
  "status": "running",
  "progress": {
    "total": 50,
    "done": 12,
    "failed": 1,
    "percent": 24
  },
  "estimated_remaining_seconds": 190,
  "articles": [
    {
      "article_id": "uuid",
      "topic": "Kỹ năng nấu ăn...",
      "status": "approved",
      "current_step": null,
      "seo_score": 0.87
    },
    {
      "article_id": "uuid",
      "topic": "Món ăn rẻ tiền...",
      "status": "generating",
      "current_step": "writing",
      "seo_score": null
    }
  ],
  "created_at": "...",
  "updated_at": "..."
}
```

Logic `estimated_remaining_seconds`:
```python
elapsed = (now - job.created_at).total_seconds()
if job.done_count > 0:
    avg = elapsed / job.done_count
    remaining = avg * (job.total_topics - job.done_count)
else:
    remaining = job.total_topics * 45  # fallback 45s/bài
```

**Sửa `app/schemas.py`** — thêm Pydantic schemas:
- `ArticleStatusItem`: article_id, topic, status, current_step, seo_score
- `JobProgress`: total, done, failed, percent
- `JobDetailResponse`: job_id, batch_name, status, progress,
  estimated_remaining_seconds, articles, created_at, updated_at

**Tối ưu query** — dùng `selectinload` tránh N+1:
```python
job = await db.execute(
    select(Job)
    .options(selectinload(Job.articles))
    .where(Job.id == job_id)
)
```

**Thêm index** vào migration hiện có (hoặc tạo migration mới):
```sql
CREATE INDEX idx_articles_job_id ON articles(job_id);
CREATE INDEX idx_articles_status ON articles(status);
```

**Test** (`tests/test_job_status.py`):
- 10 articles, 3 done, 1 failed → `percent=30`, `failed=1`
- `estimated_remaining_seconds` khi `done_count=0` → `total * 45`
- `estimated_remaining_seconds` khi `done_count=5`, `elapsed=100s` → `(100/5) * 5 = 100`
- Query không có N+1

---

## Thứ tự thực hiện

```
1. CHANGE 1  →  pytest tests/test_md_output.py      →  confirm
2. CHANGE 2A →  alembic upgrade head
               pytest tests/test_pipeline_steps.py  →  confirm
3. CHANGE 2B →  pytest tests/test_job_status.py     →  confirm
4. pytest tests/ -v  (full suite)
```

Không thay đổi interface hàm hiện có nếu không cần —
thêm params mới dùng default value để không break code cũ.
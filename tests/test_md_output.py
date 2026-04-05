"""Tests for Markdown output with YAML frontmatter."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
import frontmatter
from slugify import slugify

from app.post_processor import (
    build_markdown_with_frontmatter,
    extract_meta_description,
    PostProcessResult,
)


class TestMetaDescriptionExtraction:
    """Test meta description extraction from content."""

    def test_extract_meta_description_found(self) -> None:
        """Test extracting meta description from comment tag."""
        content = """# Title
        
<!-- meta: This is a test meta description -->

Some content here.
"""
        meta_desc, cleaned = extract_meta_description(content)
        assert meta_desc == "This is a test meta description"
        assert "<!-- meta:" not in cleaned
        assert "Some content here." in cleaned

    def test_extract_meta_description_not_found(self) -> None:
        """Test when no meta description is present."""
        content = "# Title\n\nSome content here."
        meta_desc, cleaned = extract_meta_description(content)
        assert meta_desc == ""
        assert cleaned == content

    def test_extract_meta_description_with_extra_spaces(self) -> None:
        """Test meta description with extra whitespace."""
        content = """# Title

<!--   meta:   Description with spaces   -->

Content."""
        meta_desc, cleaned = extract_meta_description(content)
        assert meta_desc == "Description with spaces"


class TestFrontmatterGeneration:
    """Test YAML frontmatter generation."""

    def test_build_markdown_with_frontmatter(self) -> None:
        """Test building complete markdown with frontmatter."""
        topic = "Kỹ năng nấu ăn"
        content = "# Kỹ năng nấu ăn\n\nSome content."
        meta_desc = "Learn cooking skills"
        seo_score = 0.87
        word_count = 350
        llm_provider = "claude"

        result = build_markdown_with_frontmatter(
            topic, content, meta_desc, seo_score, word_count, llm_provider
        )

        # Parse frontmatter
        parsed = frontmatter.loads(result)

        # Verify frontmatter fields
        assert parsed.metadata["title"] == topic
        assert parsed.metadata["meta_description"] == meta_desc
        assert parsed.metadata["seo_score"] == 0.87
        assert parsed.metadata["word_count"] == word_count
        assert parsed.metadata["llm_provider"] == llm_provider
        assert "generated_at" in parsed.metadata

        # Verify content
        assert "# Kỹ năng nấu ăn" in parsed.content
        assert "Some content." in parsed.content

        # Verify trailing newline
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_frontmatter_preserves_vietnamese(self) -> None:
        """Test that Vietnamese characters are preserved."""
        topic = "Cách nấu phở Hà Nội"
        content = "# Cách nấu phở Hà Nội\n\nHướng dẫn chi tiết."
        meta_desc = "Hướng dẫn nấu phở truyền thống"
        
        result = build_markdown_with_frontmatter(
            topic, content, meta_desc, 0.95, 500, "claude"
        )
        
        assert "Cách nấu phở Hà Nội" in result
        assert "Hướng dẫn chi tiết" in result
        assert "Hướng dẫn nấu phở truyền thống" in result


class TestSlugification:
    """Test filename slug conversion."""

    def test_slug_vietnamese_to_ascii(self) -> None:
        """Test converting Vietnamese topic to ASCII slug."""
        topic = "Kỹ năng nấu ăn"
        slug = slugify(topic, allow_unicode=False)
        assert slug == "ky-nang-nau-an"
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in slug)

    def test_slug_with_special_chars(self) -> None:
        """Test slug with special characters."""
        topic = "Tiếng Anh & Tiếng Việt"
        slug = slugify(topic, allow_unicode=False)
        # Should convert to ASCII, remove &
        assert "&" not in slug
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in slug)

    def test_slug_length_limit_80_chars(self) -> None:
        """Test slug is limited to 80 characters."""
        topic = "Đây là một chủ đề rất dài với nhiều từ để kiểm tra giới hạn độ dài của tên tệp trong ZIP" * 2
        slug = slugify(topic, allow_unicode=False)[:80]
        assert len(slug) <= 80

    def test_md_extension_added(self) -> None:
        """Test .md extension is added to slug."""
        topic = "Hướng dẫn nấu ăn"
        slug = slugify(topic, allow_unicode=False)[:80]
        filename = f"{slug}.md"
        assert filename.endswith(".md")


class TestPostProcessResult:
    """Test PostProcessResult dataclass."""

    def test_post_process_result_creation(self) -> None:
        """Test creating PostProcessResult."""
        result = PostProcessResult(
            md_content="# Title\n\nContent.",
            seo_score=0.85,
            word_count=300,
            meta_description="Test description",
            llm_provider="openai",
        )
        assert result.md_content == "# Title\n\nContent."
        assert result.seo_score == 0.85
        assert result.word_count == 300
        assert result.meta_description == "Test description"
        assert result.llm_provider == "openai"


@pytest.mark.asyncio
async def test_export_zip_with_slugified_names() -> None:
    """Test that ZIP export uses slugified filenames."""
    from unittest.mock import patch, MagicMock, AsyncMock
    from app.routers.export import export_articles

    # Create mock articles
    article1 = MagicMock()
    article1.topic = "Kỹ năng nấu ăn"
    article1.md_content = "---\ntitle: Kỹ năng nấu ăn\n---\n# Content"
    article1.content = None
    
    article2 = MagicMock()
    article2.topic = "Cách học Tiếng Anh"
    article2.md_content = "---\ntitle: Cách học Tiếng Anh\n---\n# Content 2"
    article2.content = None
    
    # Mock the database result
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [article1, article2]
    
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    
    # Call export
    response = await export_articles(job_id=None, db=mock_db)
    
    # Extract ZIP content
    zip_data = io.BytesIO()
    async for chunk in response.body_iterator:
        zip_data.write(chunk)
    
    zip_data.seek(0)
    with zipfile.ZipFile(zip_data) as zf:
        names = zf.namelist()
        # Should have slugified names
        assert any("ky-nang-nau-an" in name for name in names)
        assert any("cach-hoc-tieng-anh" in name for name in names)

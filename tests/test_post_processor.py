"""Tests for post_processor module."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.post_processor import count_words, save_markdown, validate_content

SAMPLE_RULES = {
    "seo": {"min_word_count": 800},
    "validation": {
        "min_word_count": 50,
        "required_sections": ["title", "introduction", "conclusion"],
    },
}

VALID_CONTENT = """# Tiêu đề bài viết hay

> **Meta:** Đây là mô tả meta ngắn gọn súc tích dưới 160 ký tự để kiểm thử.

## Giới thiệu

Đây là phần giới thiệu về bài viết. Nội dung dài đủ để kiểm tra việc đếm từ và validate.
Thêm nhiều văn bản vào đây để đảm bảo đủ từ.

## Nội dung chính

### Phần 1

Nội dung phần một.

### Phần 2

Nội dung phần hai.

### Phần 3

Nội dung phần ba.

## Kết luận

Đây là phần kết luận của bài viết.
"""


def test_count_words():
    assert count_words("hello world") == 2
    assert count_words("  ") == 0
    assert count_words("Hà Nội Việt Nam") == 4


def test_validate_content_valid():
    errors = validate_content(VALID_CONTENT, rules=SAMPLE_RULES)
    assert errors == []


def test_validate_content_missing_title():
    content = "## Section\n\nText\n\n## Another\n\nkết luận"
    errors = validate_content(content, rules=SAMPLE_RULES)
    assert any("H1" in e for e in errors)


def test_validate_content_too_short():
    short_rules = {
        "validation": {"min_word_count": 10000, "required_sections": []},
        "seo": {},
    }
    errors = validate_content("Short content here", rules=short_rules)
    assert any("Word count" in e for e in errors)


def test_validate_content_missing_h2():
    content = "# Title\n\nIntroduction text that is long enough.\n\nkết luận"
    errors = validate_content(content, rules=SAMPLE_RULES)
    assert any("H2" in e for e in errors)


def test_save_markdown(tmp_path):
    content = "# Test\n\nContent here."
    out = save_markdown(content, tmp_path / "sub" / "test.md")
    assert out.exists()
    assert out.read_text(encoding="utf-8") == content


def test_save_markdown_creates_parents(tmp_path):
    content = "# Deep\n\nContent."
    deep = tmp_path / "a" / "b" / "c" / "article.md"
    result = save_markdown(content, deep)
    assert result.exists()

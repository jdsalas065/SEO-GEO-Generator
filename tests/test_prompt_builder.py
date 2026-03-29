"""Tests for prompt_builder module."""
from __future__ import annotations

from app.prompt_builder import build_prompt


SAMPLE_RULES = {
    "seo": {
        "min_word_count": 800,
        "max_word_count": 1500,
        "tone": "informative",
        "language": "vi",
    },
    "geo": {
        "target_country": "VN",
        "locale": "vi-VN",
    },
    "content": {
        "include_faq": True,
        "faq_count": 5,
    },
}


def test_build_prompt_contains_topic():
    prompt = build_prompt("Ẩm thực Hà Nội", rules=SAMPLE_RULES)
    assert "Ẩm thực Hà Nội" in prompt


def test_build_prompt_contains_keyword():
    prompt = build_prompt("Test topic", keyword="test kw", rules=SAMPLE_RULES)
    assert "test kw" in prompt


def test_build_prompt_no_keyword_no_keyword_line():
    prompt = build_prompt("No keyword topic", rules=SAMPLE_RULES)
    assert "Primary keyword" not in prompt


def test_build_prompt_with_review_note():
    prompt = build_prompt("Topic", review_note="Add more examples", rules=SAMPLE_RULES)
    assert "Add more examples" in prompt
    assert "Previous review feedback" in prompt


def test_build_prompt_faq_section():
    prompt = build_prompt("Topic", rules=SAMPLE_RULES)
    assert "FAQ" in prompt


def test_build_prompt_no_faq_when_disabled():
    rules = {**SAMPLE_RULES, "content": {"include_faq": False}}
    prompt = build_prompt("Topic", rules=rules)
    assert "FAQ" not in prompt


def test_build_prompt_word_count_range():
    prompt = build_prompt("Topic", rules=SAMPLE_RULES)
    assert "800" in prompt
    assert "1500" in prompt

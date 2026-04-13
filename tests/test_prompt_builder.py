"""Tests for prompt_builder module."""
from __future__ import annotations

from app.prompt_builder import (
    build_fallback_outline,
    build_outline_prompt,
    build_prompt,
    build_write_prompt,
)


SAMPLE_RULES = {
    "seo": {
        "min_word_count": 800,
        "max_word_count": 1500,
        "tone": "informative",
        "language": "vi",
    },
    "geo": {
        "eeat_level": "basic",
        "snippet_position": "top",
        "reader_awareness": True,
        "geo_principles": [
            "answer_first",
            "real_examples",
            "semantic_over_keyword",
            "entity_building",
            "short_paragraphs",
        ],
        "target_country": "VN",
        "locale": "vi-VN",
        "local_entities": True,
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


def test_build_prompt_contains_geo_guidance():
    prompt = build_prompt("Test topic", rules=SAMPLE_RULES)
    assert "answer_first" in prompt.lower()
    assert "semantic_over_keyword" in prompt.lower()
    assert "reader_awareness" in prompt.lower()


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


def test_build_write_prompt_requires_conclusion():
    outline = {
        "h1": "Test H1",
        "search_intent": "informational",
        "reader_stage": "considering",
        "sections": [{"h2": "Section 1", "h3s": ["Sub 1"], "key_points": ["Point 1", "Point 2"]}],
        "keywords": ["test"],
        "faq": [{"q": "Q1?", "a": "A1"}],
    }

    prompt = build_write_prompt("Topic", outline, config=SAMPLE_RULES, review_note="Cần thêm ví dụ thật")

    assert "## Kết luận" in prompt["user"]
    assert "Treat the structure below as the primary guide" in prompt["user"]
    assert "Cần thêm ví dụ thật" in prompt["user"]
    assert "answer_first" in prompt["user"].lower()
    assert "reader stage (considering)" in prompt["user"].lower()
    assert "search intent: informational" in prompt["user"].lower()


def test_build_write_prompt_includes_keyword_and_reference_outline():
    outline = {
        "h1": "Test H1",
        "search_intent": "informational",
        "reader_stage": "curious",
        "sections": [{"h2": "Section 1", "h3s": [], "key_points": ["Point 1", "Point 2"]}],
        "keywords": ["test"],
        "faq": [],
    }
    prompt = build_write_prompt(
        "Topic",
        outline,
        config=SAMPLE_RULES,
        keyword="vé máy bay đi nhật bản 2026",
        reference_outline={"H2": ["Giới thiệu điểm đến"]},
    )

    assert "vé máy bay đi nhật bản 2026" in prompt["user"]
    assert "Reference outline" in prompt["user"]
    assert "do not copy verbatim" in prompt["user"].lower()


def test_build_outline_prompt_has_reader_fields():
    prompt = build_outline_prompt(
        "Kỹ năng nấu ăn",
        config=SAMPLE_RULES,
        keyword="học nấu ăn",
        reference_outline={"H2": ["Giới thiệu"]},
    )
    assert "search_intent" in prompt["user"]
    assert "reader_stage" in prompt["user"]
    assert "học nấu ăn" in prompt["user"]
    assert "Reference input" in prompt["user"]


def test_build_fallback_outline_has_reader_fields():
    outline = build_fallback_outline("Máy lọc không khí", config=SAMPLE_RULES)
    assert outline["search_intent"] == "informational"
    assert outline["reader_stage"] == "curious"

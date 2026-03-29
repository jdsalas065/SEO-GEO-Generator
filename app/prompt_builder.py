"""Build SEO/GEO prompts from rules.yaml configuration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_RULES_PATH = Path(__file__).parent.parent / "config" / "rules.yaml"


def load_rules(path: Path = _RULES_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_prompt(
    topic: str,
    keyword: str | None = None,
    review_note: str | None = None,
    rules: dict[str, Any] | None = None,
) -> str:
    """Return a fully-formed system+user prompt string."""
    if rules is None:
        rules = load_rules()

    seo = rules.get("seo", {})
    geo = rules.get("geo", {})
    content_cfg = rules.get("content", {})

    min_words = seo.get("min_word_count", 800)
    max_words = seo.get("max_word_count", 1500)
    tone = seo.get("tone", "informative")
    language = seo.get("language", "vi")
    locale = geo.get("locale", "vi-VN")
    country = geo.get("target_country", "VN")
    include_faq = content_cfg.get("include_faq", True)
    faq_count = content_cfg.get("faq_count", 5)

    keyword_line = (
        f"- Primary keyword: **{keyword}** (target density 1–3%)\n" if keyword else ""
    )
    faq_line = (
        f"- Include a FAQ section with exactly {faq_count} questions and answers.\n"
        if include_faq
        else ""
    )
    review_section = (
        f"\n\n## Previous review feedback (must be addressed)\n{review_note}\n"
        if review_note
        else ""
    )

    prompt = f"""You are an expert Vietnamese content writer specialising in SEO and GEO (Generative Engine Optimisation).

Write a complete, publication-ready article in Markdown format for the following topic.

## Topic
{topic}{review_section}

## Requirements
- Language: {language} ({locale})
- Target country/region: {country}
- Tone: {tone}
- Word count: {min_words}–{max_words} words
- Structure: at least 2 × H2 headings and 3 × H3 headings
- Start with a compelling title (H1)
- Include an introduction and a conclusion
{keyword_line}{faq_line}
## SEO rules
- Meta description (160 chars max) as a blockquote at the very top of the document (format: `> **Meta:** <text>`)
- Use the primary keyword naturally; avoid keyword stuffing
- Use local Vietnamese entities (businesses, places, cultural references) where relevant

## GEO rules
- Write concise, factual sentences that can be extracted as AI snippets
- Include at least one definition or "What is X?" answer
- Use structured lists and tables where appropriate

## Output
Return ONLY the Markdown article — no extra commentary, no code fences.
"""
    return prompt.strip()

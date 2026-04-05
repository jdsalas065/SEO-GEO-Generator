"""Build SEO/GEO prompts from rules.yaml configuration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

_RULES_PATH = Path(__file__).parent.parent / "config" / "rules.yaml"


def load_rules(path: Path = _RULES_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_outline_prompt(
    topic: str,
    config: dict[str, Any] | None = None,
    review_note: str = "",
) -> dict[str, str]:
    """
    Build outline/structure prompt for step 1.
    
    Returns a dict with:
    {
      "h1": "...",
      "sections": [
        {"h2": "...", "h3s": ["..."], "key_points": ["..."]}
      ],
      "keywords": ["..."],
      "faq": [{"q": "...", "a": "..."}, ...]  // exactly 5 items
    }
    """
    if config is None:
        config = load_rules()
    
    seo = config.get("seo", {})
    content_cfg = config.get("content", {})
    geo = config.get("geo", {})
    
    tone = seo.get("tone", "informative")
    language = seo.get("language", "vi")
    locale = geo.get("locale", "vi-VN")
    country = geo.get("target_country", "VN")
    include_faq = content_cfg.get("include_faq", True)
    faq_count = content_cfg.get("faq_count", 5)
    
    review_section = (
        f"\n\n## Previous review feedback (must be addressed)\n{review_note}\n"
        if review_note
        else ""
    )
    
    faq_instruction = (
        f"- Create exactly {faq_count} FAQ question-answer pairs relevant to the topic"
        if include_faq
        else ""
    )
    
    system_prompt = """You are an expert Vietnamese content strategist specialising in SEO and GEO (Generative Engine Optimisation).

Your task is to create a detailed article structure/outline for a given topic."""
    
    user_prompt = f"""Create a structured outline (return ONLY valid JSON, no markdown) for this topic:

Topic: {topic}{review_section}

Requirements:
- Language: {language} ({locale})
- Target country: {country}
- Tone: {tone}
- Include at least 2 main sections (H2)
- Each section should have 1-2 subsections (H3)
- Include 3-5 key points per section
{faq_instruction}

Return this JSON structure (NO markdown code fences):
{{
  "h1": "Main heading (maximum 8 words)",
  "sections": [
    {{
      "h2": "Section heading",
      "h3s": ["Subsection 1", "Subsection 2"],
      "key_points": ["Point 1", "Point 2", "Point 3"]
    }}
  ],
  "keywords": ["keyword1", "keyword2", "keyword3"],
  "faq": [
    {{"q": "Question 1?", "a": "Brief answer"}},
    {{"q": "Question 2?", "a": "Brief answer"}}
  ]
}}"""
    
    return {"system": system_prompt, "user": user_prompt}


def build_write_prompt(
    topic: str,
    outline: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """
    Build writing prompt for step 2.
    Injects the outline to ensure the article follows the structure exactly.
    """
    if config is None:
        config = load_rules()
    
    seo = config.get("seo", {})
    geo = config.get("geo", {})
    
    min_words = seo.get("min_word_count", 800)
    max_words = seo.get("max_word_count", 1500)
    tone = seo.get("tone", "informative")
    language = seo.get("language", "vi")
    locale = geo.get("locale", "vi-VN")
    country = geo.get("target_country", "VN")
    
    # Extract structure from outline
    h1 = outline.get("h1", topic)
    sections_json = json.dumps(outline.get("sections", []), ensure_ascii=False, indent=2)
    keywords = outline.get("keywords", [])
    faq = outline.get("faq", [])
    
    keywords_line = ", ".join(keywords) if keywords else ""
    
    system_prompt = """You are an expert Vietnamese content writer specialising in SEO and GEO (Generative Engine Optimisation).

Your task is to write a complete publication-ready article following the provided outline exactly."""
    
    user_prompt = f"""Write a complete Markdown article with the following details:

Topic: {topic}
H1 Title: {h1}

Language: {language} ({locale})
Target country: {country}
Tone: {tone}
Word count: {min_words}–{max_words} words
Keywords to use naturally: {keywords_line}

CRITICAL: Follow this structure exactly. Do NOT add, remove, or reorder sections:
{sections_json}

Write FAQ section as H2 heading with {len(faq)} Q&A pairs based on this template:
{json.dumps(faq, ensure_ascii=False, indent=2)}

Format:
- Start with H1: # {h1}
- Write introduction (2-3 sentences) that directly answers the main question
- Follow sections in exact order from the structure above
- Use H2 (##) for main sections and H3 (###) for subsections
- End with FAQ section (## FAQ)
- Include a meta description as HTML comment at the top: <!-- meta: concise description (max 160 chars) -->

Output ONLY the Markdown article — no extra commentary or markdown code fences."""
    
    return {"system": system_prompt, "user": user_prompt}


def build_seo_check_prompt(
    topic: str,
    article_md: str,
    config: dict[str, Any] | None = None,
) -> dict[str, str]:
    """
    Build SEO validation prompt for step 3.
    
    Returns dict with keys:
    {{
      "meta_description": "...",  // 150-160 ký tự tiếng Việt
      "issues": ["..."],          // SEO issues or []
      "geo_score": 0.0            // 0.0-1.0
    }}
    """
    if config is None:
        config = load_rules()
    
    seo = config.get("seo", {})
    
    min_words = seo.get("min_word_count", 800)
    max_words = seo.get("max_word_count", 1500)
    meta_max = seo.get("meta_description_max_length", 160)
    
    system_prompt = """You are an expert SEO and GEO auditor for Vietnamese content.

Analyze the provided article and return JSON with SEO insights."""
    
    user_prompt = f"""Analyze this article for SEO quality and return ONLY valid JSON (no markdown):

Topic: {topic}
Article:
{article_md}

Check for:
1. Appropriate word count ({min_words}–{max_words} words)
2. Clear H1 and multiple H2/H3 sections
3. FAQ section with Q&A pairs
4. Natural keyword integration
5. Snippet-friendly structure for AI extraction

Return exactly this JSON (NO markdown code fences):
{{
  "meta_description": "Concise description suitable for search results (max {meta_max} characters, Vietnamese)",
  "issues": [
    "issue1 if found, [] if perfect"
  ],
  "geo_score": 0.85
}}

Score guidance:
- 0.9-1.0: Excellent SEO, ready to publish
- 0.7-0.89: Good SEO, minor improvements suggested
- 0.5-0.69: Acceptable but needs work
- <0.5: Significant issues"""
    
    return {"system": system_prompt, "user": user_prompt}


def build_prompt(
    topic: str,
    keyword: str | None = None,
    review_note: str | None = None,
    rules: dict[str, Any] | None = None,
) -> str:
    """Return a fully-formed system+user prompt string (legacy single-step API)."""
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

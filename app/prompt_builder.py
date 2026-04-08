"""Build SEO/GEO prompts from rules.yaml configuration."""
from __future__ import annotations

import json
import re
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
- Use exactly 2 main sections (H2)
- Each section should have 1-2 subsections (H3)
- Include exactly 2 short key points per section
- Keep each string concise (max 80 chars)
{faq_instruction}

Return this JSON structure (NO markdown code fences):
{{
  "h1": "Main heading (maximum 8 words)",
  "sections": [
    {{
      "h2": "Section heading",
      "h3s": ["Subsection 1", "Subsection 2"],
            "key_points": ["Point 1", "Point 2"]
    }}
  ],
  "keywords": ["keyword1", "keyword2", "keyword3"],
  "faq": [
    {{"q": "Question 1?", "a": "Brief answer"}},
    {{"q": "Question 2?", "a": "Brief answer"}}
  ]
}}"""
    
    return {"system": system_prompt, "user": user_prompt}


def build_fallback_outline(topic: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a deterministic outline when LLM JSON cannot be parsed."""
    if config is None:
        config = load_rules()

    content_cfg = config.get("content", {})
    include_faq = bool(content_cfg.get("include_faq", True))
    faq_count = int(content_cfg.get("faq_count", 5))

    words = re.findall(r"\w+", topic.lower(), flags=re.UNICODE)
    keywords: list[str] = []
    for w in words:
        if len(w) < 3:
            continue
        if w not in keywords:
            keywords.append(w)
        if len(keywords) == 5:
            break

    if not keywords:
        keywords = ["huong dan", "kinh nghiem", "gia dinh"]

    def _build_faq_item(index: int, topic_text: str) -> dict[str, str]:
        topic_terms = topic_text.split()
        lead_term = topic_terms[0] if topic_terms else "chu de nay"
        templates = [
            (
                f"{topic_text} phu hop voi doi tuong nao?",
                "Phu hop voi nguoi moi bat dau va nguoi can giai phap thuc te.",
            ),
            (
                f"Nen uu tien tieu chi nao khi chon {topic_text}?",
                "Nen uu tien muc tieu su dung, ngan sach va kha nang van hanh lau dai.",
            ),
            (
                f"{topic_text} thuong gap nhung loi nao?",
                "Thuong gap viec chon sai nhu cau thuc te va bo qua buoc danh gia ket qua.",
            ),
            (
                f"Bao lau nen danh gia lai hieu qua cua {topic_text}?",
                "Nen danh gia dinh ky sau moi giai doan su dung de dieu chinh kip thoi.",
            ),
            (
                f"Lam sao de toi uu chi phi khi ap dung {topic_text}?",
                "Bat dau voi phuong an can bang chi phi-hieu qua, sau do toi uu theo du lieu thuc te.",
            ),
            (
                f"Can theo doi chi so nao de do hieu qua cua {topic_text}?",
                "Theo doi ket qua dau ra, muc do on dinh va chi phi van hanh theo thoi gian.",
            ),
            (
                f"Khi nao nen chuyen sang phuong an khac cho {lead_term}?",
                "Khi chi phi vuot muc, hieu qua giam hoac nhu cau da thay doi ro rang.",
            ),
        ]
        question, answer = templates[index % len(templates)]
        return {"q": question, "a": answer}

    faq: list[dict[str, str]] = []
    if include_faq:
        topic_short = topic.strip() or "chu de nay"
        faq = [_build_faq_item(i, topic_short) for i in range(max(0, faq_count))]

    return {
        "h1": topic.strip()[:120] or "Huong dan thuc te",
        "sections": [
            {
                "h2": "Nhu cau su dung va muc tieu uu tien",
                "h3s": ["Xac dinh boi canh su dung", "Dat muc tieu cu the"],
                "key_points": [
                    "Danh gia nhu cau theo tinh huong thuc te.",
                    "Can bang giua hieu qua, chi phi va do ben.",
                ],
            },
            {
                "h2": "Cach chon giai phap phu hop va toi uu",
                "h3s": ["So sanh cac lua chon", "Kiem tra va toi uu van hanh"],
                "key_points": [
                    "So sanh theo tieu chi ro rang va co uu tien.",
                    "Theo doi ket qua de dieu chinh kip thoi.",
                ],
            },
        ],
        "keywords": keywords,
        "faq": faq,
    }


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
- Include a final H2 conclusion section before the FAQ, titled exactly '## Kết luận'
- Do not omit the conclusion section; the article must end with a short closing summary
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

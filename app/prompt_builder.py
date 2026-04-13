"""Build SEO/GEO prompts from rules.yaml configuration."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

_RULES_PATH = Path(__file__).parent.parent / "config" / "rules.yaml"


def _geo_principles(geo: dict[str, Any]) -> list[str]:
    principles = geo.get("geo_principles", [])
    if isinstance(principles, list):
        return [str(item).strip() for item in principles if str(item).strip()]
    return []


def _geo_guidance_lines(
    geo: dict[str, Any],
    *,
    include_reader_awareness: bool = False,
) -> list[str]:
    eeat_level = str(geo.get("eeat_level", "basic")).lower()
    snippet_position = str(geo.get("snippet_position", "top")).lower()
    reader_awareness = bool(geo.get("reader_awareness", False))
    local_entities = bool(geo.get("local_entities", False))

    lines = [
        f"- snippet_position: {snippet_position}",
        f"- eeat_level: {eeat_level}",
    ]

    if reader_awareness and include_reader_awareness:
        lines.append(
            "- reader_awareness: curious / considering / deciding"
        )

    if local_entities:
        lines.append(
            "- local_entities: include brand/place signals when relevant"
        )

    for principle in _geo_principles(geo):
        if principle == "answer_first":
            lines.append("- answer_first: answer directly before explaining")
        elif principle == "real_examples":
            lines.append("- real_examples: use concrete examples/case studies")
        elif principle == "semantic_over_keyword":
            lines.append("- semantic_over_keyword: cover concepts, not keyword stuffing")
        elif principle == "entity_building":
            lines.append(
                "- entity_building: name relevant people, brands, organizations"
            )
        elif principle == "short_paragraphs":
            lines.append("- short_paragraphs: keep paragraphs to 2-4 sentences")
        else:
            lines.append(f"- GEO principle: {principle}")

    if eeat_level == "ymyl":
        lines.append(
            "- ymyl: require expert review and trustworthy sources"
        )

    return lines


def load_rules(path: Path = _RULES_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _format_outline_reference(reference_outline: Any | None) -> str:
    """Render an optional outline reference as readable prompt text."""
    if reference_outline is None:
        return ""

    if isinstance(reference_outline, str):
        outline_text = reference_outline.strip()
        if not outline_text:
            return ""
        try:
            parsed_outline = json.loads(outline_text)
        except json.JSONDecodeError:
            return outline_text
        outline_text = json.dumps(parsed_outline, ensure_ascii=False, indent=2)
    else:
        try:
            outline_text = json.dumps(reference_outline, ensure_ascii=False, indent=2)
        except TypeError:
            outline_text = str(reference_outline).strip()

    if not outline_text.strip():
        return ""

    return (
        "Reference outline (soft guidance only, do not copy verbatim):\n"
        f"{outline_text}\n"
        "Use the ideas, hierarchy, and intent as inspiration, but you may rewrite headings "
        "and reorder nearby points if that improves clarity and natural flow."
    )


def build_outline_prompt(
    topic: str,
    config: dict[str, Any] | None = None,
    review_note: str = "",
    keyword: str | None = None,
    reference_outline: Any | None = None,
) -> dict[str, str]:
    """
    Build 
    
    /structure prompt for step 1.
    
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

    keyword_instruction = (
        f"- Primary keyword: {keyword}\n- Use the primary keyword and close semantic variants to shape the outline"
        if keyword
        else ""
    )
    outline_reference_block = _format_outline_reference(reference_outline)
    outline_reference_section = (
        f"\n\nReference input for inspiration only:\n{outline_reference_block}\n"
        if outline_reference_block
        else ""
    )

    reader_stage_instruction = """
Search intent: informational / commercial / navigational.
Reader stage: one of curious, considering, deciding.
Choose the most likely values for this topic and audience.
""".strip()

    geo_lines = _geo_guidance_lines(geo, include_reader_awareness=True)
    geo_block = "\n".join(geo_lines)
    
    system_prompt = """You are an expert Vietnamese content strategist specialising in SEO and GEO (Generative Engine Optimisation).

Your task is to create a detailed article structure/outline for a given topic."""
    
    user_prompt = f"""Create a structured outline (return ONLY valid JSON, no markdown) for this topic:

Topic: {topic}{review_section}
{outline_reference_section}

Requirements:
- Language: {language} ({locale})
- Target country: {country}
- Tone: {tone}
- {reader_stage_instruction}
- Keep the output aligned with the user's intent, not a verbatim copy of any reference outline
- Prefer headings that match the topic and keyword naturally when possible
{keyword_instruction}
- Use exactly 2 main sections (H2)
- Each section should have 1-2 subsections (H3)
- Include exactly 2 short key points per section
- Keep strings concise (max 80 chars)
{geo_block}
{faq_instruction}

Return this JSON structure (NO markdown code fences):
{{
    "search_intent": "informational",
    "reader_stage": "curious",
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

    search_intent = "informational"
    reader_stage = "curious"

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
        "search_intent": search_intent,
        "reader_stage": reader_stage,
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
    review_note: str | None = None,
    keyword: str | None = None,
    reference_outline: Any | None = None,
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
    keywords = list(outline.get("keywords", []))
    if keyword and keyword not in keywords:
        keywords.insert(0, keyword)
    faq = outline.get("faq", [])
    search_intent = str(outline.get("search_intent", "informational")).lower()
    reader_stage = str(outline.get("reader_stage", "curious")).lower()
    eeat_level = str(geo.get("eeat_level", "basic")).lower()
    snippet_position = str(geo.get("snippet_position", "top")).lower()

    stage_instruction = {
        "curious": "Giải thích đơn giản, dùng ví dụ đời thường.",
        "considering": "So sánh ưu nhược, giúp người đọc cân nhắc.",
        "deciding": "Cụ thể, thực tế, trả lời nỗi lo chốt quyết định.",
    }.get(reader_stage, "")
    
    keywords_line = ", ".join(keywords) if keywords else ""
    keyword_line = (
        f"- Primary keyword: **{keyword}** (use it naturally in the H1, intro, and relevant H2/H3 headings when it fits)\n"
        if keyword
        else ""
    )
    outline_reference_block = _format_outline_reference(reference_outline)
    outline_reference_section = (
        f"\n\nReference outline (soft guidance only):\n{outline_reference_block}\n"
        if outline_reference_block
        else ""
    )
    review_section = (
        f"\n\n## Previous review feedback (must be addressed)\n{review_note}\n"
        if review_note
        else ""
    )
    geo_lines = _geo_guidance_lines(geo)
    geo_block = "\n".join(geo_lines)
    
    system_prompt = """You are an expert Vietnamese content writer specialising in SEO and GEO (Generative Engine Optimisation).

Your task is to write a complete publication-ready article following the provided outline exactly."""
    
    user_prompt = f"""Write a complete Markdown article with the following details:

Topic: {topic}
H1 Title: {h1}
{review_section}
{outline_reference_section}

Language: {language} ({locale})
Target country: {country}
Tone: {tone}
Word count: {min_words}–{max_words} words
{keyword_line}
Keywords to use naturally: {keywords_line}
Search intent: {search_intent}

GEO guidance:
{geo_block}

Article behavior:
- Put the first compact answer near the top of the article, following snippet_position={snippet_position}
- Keep the opening section direct and easy for AI extraction
- Reader stage ({reader_stage}): {stage_instruction}
- Prefer semantic coverage, entity signals, and concrete examples over repeating the keyword
- Use 2-4 sentence paragraphs and bullets where the structure benefits scanning
- If eeat_level is ymyl, include expert-reviewed wording, citations, or source references where appropriate
- H2/H3 headings should read like questions or clear benefits when possible

CRITICAL: Treat the structure below as the primary guide. Keep the same intent and overall order, but you may refine wording or make small structural adjustments if they improve clarity:
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
- Meta description should answer the main query directly and reflect the reader stage

Output ONLY the Markdown article — no extra commentary or markdown code fences."""
    
    return {"system": system_prompt, "user": user_prompt}


def build_seo_check_prompt(
    topic: str,
    article_md: str,
    config: dict[str, Any] | None = None,
    reader_stage: str | None = None,
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
    geo = config.get("geo", {})
    
    min_words = seo.get("min_word_count", 800)
    max_words = seo.get("max_word_count", 1500)
    meta_max = seo.get("meta_description_max_length", 160)
    geo_lines = _geo_guidance_lines(geo)
    geo_block = "\n".join(geo_lines)
    stage_instruction = {
        "curious": "Check if the opening explains clearly for beginners.",
        "considering": "Check if the article compares options and tradeoffs.",
        "deciding": "Check if the article handles final objections and action cues.",
    }.get(str(reader_stage or "").lower(), "")
    
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
6. Answer-first structure, semantic depth, entity signals, and short paragraphs
{geo_block}
{stage_instruction}

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
    geo_lines = _geo_guidance_lines(geo, include_reader_awareness=True)
    geo_block = "\n".join(geo_lines)

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
{geo_block}
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

"""Validate LLM output and save as Markdown files."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_RULES_PATH = Path(__file__).parent.parent / "config" / "rules.yaml"


def _load_rules() -> dict[str, Any]:
    with _RULES_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def count_words(text: str) -> int:
    """Count whitespace-separated tokens (works for Vietnamese)."""
    return len(text.split())


@dataclass
class PostProcessResult:
    """Result of post-processing an article."""
    md_content: str  # Full markdown with YAML frontmatter
    seo_score: float  # 0.0-1.0
    word_count: int
    meta_description: str
    llm_provider: str  # "claude", "openai", "gemini"


def extract_meta_description(content: str) -> tuple[str, str]:
    """
    Extract meta description from <!-- meta: ... --> tag in content.
    Returns (meta_description, cleaned_content_without_meta_tag).
    If no meta tag found, returns ("", original_content).
    """
    pattern = r'<!--\s*meta:\s*(.+?)\s*-->'
    match = re.search(pattern, content)
    if match:
        meta_desc = match.group(1).strip()
        cleaned = content[:match.start()] + content[match.end():]
        return meta_desc, cleaned
    return "", content


def build_markdown_with_frontmatter(
    topic: str,
    content: str,
    meta_description: str,
    seo_score: float,
    word_count: int,
    llm_provider: str,
) -> str:
    """
    Build complete markdown file with YAML frontmatter.
    Returns the full markdown string with exactly 1 trailing newline.
    """
    frontmatter = {
        "title": topic,
        "meta_description": meta_description,
        "seo_score": round(seo_score, 2),
        "word_count": word_count,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "llm_provider": llm_provider,
    }
    
    fm_yaml = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)
    
    # Build: --- \n frontmatter \n --- \n content \n
    result = f"---\n{fm_yaml}---\n{content.rstrip()}\n"
    return result


def validate_content(content: str, rules: dict[str, Any] | None = None) -> list[str]:
    """
    Validate article content against rules.yaml.
    Returns a list of validation error messages (empty = valid).
    """
    if rules is None:
        rules = _load_rules()

    errors: list[str] = []
    validation = rules.get("validation", {})
    seo = rules.get("seo", {})

    # Word count check
    word_count = count_words(content)
    min_wc = validation.get("min_word_count", seo.get("min_word_count", 600))
    if word_count < min_wc:
        errors.append(f"Word count {word_count} is below minimum {min_wc}")

    # Required sections
    required = validation.get("required_sections", ["title", "introduction", "conclusion"])
    lower_content = content.lower()

    if "title" in required:
        if not re.search(r"^#\s+\S", content, re.MULTILINE):
            errors.append("Missing H1 title")

    if "introduction" in required:
        # Heuristic: content has non-heading paragraph before first H2
        if not re.search(r"(?:introduction|giới thiệu|mở đầu|tổng quan)", lower_content):
            # Lenient: just check there's text before the first H2
            first_h2 = re.search(r"^##\s", content, re.MULTILINE)
            h1 = re.search(r"^#\s", content, re.MULTILINE)
            if first_h2 and h1:
                intro_text = content[h1.end():first_h2.start()].strip()
                if len(intro_text) < 50:
                    errors.append("Introduction section appears missing or too short")

    if "conclusion" in required:
        if not re.search(r"(?:conclusion|kết luận|tổng kết|kết)", lower_content):
            errors.append("Conclusion section appears missing")

    # H2 headings
    min_h2 = 2
    h2_count = len(re.findall(r"^##\s", content, re.MULTILINE))
    if h2_count < min_h2:
        errors.append(f"Requires at least {min_h2} H2 headings, found {h2_count}")

    return errors


def calculate_seo_score(content: str, rules: dict[str, Any] | None = None) -> float:
    """
    Calculate a simple SEO score (0.0-1.0) based on content structure.
    """
    if rules is None:
        rules = _load_rules()
    
    score = 0.0
    max_score = 1.0
    
    # Word count (max 0.3)
    word_count = count_words(content)
    seo_rules = rules.get("seo", {})
    min_wc = seo_rules.get("min_word_count", 600)
    ideal_wc = seo_rules.get("ideal_word_count", 1500)
    
    if word_count >= ideal_wc:
        score += 0.3
    elif word_count >= min_wc:
        score += (word_count - min_wc) / (ideal_wc - min_wc) * 0.3
    
    # H1 title (max 0.2)
    if re.search(r"^#\s+\S", content, re.MULTILINE):
        score += 0.2
    
    # H2 headings (max 0.2)
    h2_count = len(re.findall(r"^##\s", content, re.MULTILINE))
    if h2_count >= 3:
        score += 0.2
    elif h2_count >= 2:
        score += h2_count / 3 * 0.2
    
    # FAQ section (max 0.15)
    if re.search(r"##\s+(?:FAQ|Các câu hỏi|Hỏi đáp|Q&A)", content, re.IGNORECASE):
        score += 0.15
    
    # Meta keywords in intro (max 0.15)
    intro_match = re.search(r"^#\s+.+?\n+(.+?)(?:^##|\Z)", content, re.MULTILINE | re.DOTALL)
    if intro_match:
        intro = intro_match.group(1).lower()
        if len(intro) > 0:
            score += 0.15
    
    return min(score, max_score)


def save_markdown(content: str, output_path: Path) -> Path:
    """Write content to a .md file, creating parent directories if needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path

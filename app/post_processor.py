"""Validate LLM output and save as Markdown files."""
from __future__ import annotations

import re
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


def save_markdown(content: str, output_path: Path) -> Path:
    """Write content to a .md file, creating parent directories if needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path

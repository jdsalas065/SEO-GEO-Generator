"""Parse Excel (.xlsx) and JSON input files into a list of topic dicts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import openpyxl


def _normalise(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw row dict to {topic, keyword, outline}."""
    # Accept flexible column names
    topic_keys = ("topic", "Topic", "TOPIC", "chủ đề", "title", "Title")
    keyword_keys = ("keyword", "Keyword", "KEYWORD", "từ khóa", "key")
    outline_keys = ("outline", "Outline", "OUTLINE", "dàn ý", "dan y")

    topic: str | None = None
    keyword: str | None = None
    outline: Any | None = None

    for k in topic_keys:
        if k in row and row[k]:
            topic = str(row[k]).strip()
            break

    for k in keyword_keys:
        if k in row and row[k]:
            keyword = str(row[k]).strip()
            break

    for k in outline_keys:
        if k in row and row[k]:
            outline_value = row[k]
            if isinstance(outline_value, str):
                outline_text = outline_value.strip()
                if outline_text:
                    try:
                        outline = json.loads(outline_text)
                    except json.JSONDecodeError:
                        outline = outline_text
            else:
                outline = outline_value
            break

    if not topic:
        return {}  # type: ignore[return-value]  # sentinel: caller skips empty dicts

    return {"topic": topic, "keyword": keyword, "outline": outline}


def parse_excel(path: Path) -> list[dict[str, Any]]:
    """Read first sheet of an xlsx file, return list of normalised rows."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    results: list[dict[str, Any]] = []

    for row_values in rows[1:]:
        row = dict(zip(headers, row_values))
        normalised = _normalise(row)
        if normalised:
            results.append(normalised)

    return results


def parse_json(path: Path) -> list[dict[str, Any]]:
    """Read a JSON file: accepts list of objects or {topics: [...]}."""
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, dict):
        # Support {"topics": [...]} envelope
        data = data.get("topics", data.get("articles", list(data.values())[0]))

    if not isinstance(data, list):
        raise ValueError("JSON must contain a list of topic objects")

    results: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, str):
            item = {"topic": item}
        normalised = _normalise(item)
        if normalised:
            results.append(normalised)

    return results


def parse_input(path: Path) -> list[dict[str, Any]]:
    """Dispatch to excel or json parser based on file extension."""
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return parse_excel(path)
    elif suffix == ".json":
        return parse_json(path)
    else:
        raise ValueError(f"Unsupported file format: {suffix!r}")

"""Tests for input_parser module."""
from __future__ import annotations

import json
from pathlib import Path

import openpyxl
import pytest

from app.input_parser import parse_excel, parse_json, parse_input


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


def make_xlsx(path: Path, rows: list[dict]) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    if rows:
        headers = list(rows[0].keys())
        ws.append(headers)
        for row in rows:
            ws.append([row.get(h) for h in headers])
    wb.save(path)
    return path


def test_parse_excel_basic(tmp_dir):
    xlsx = make_xlsx(
        tmp_dir / "topics.xlsx",
        [
            {"topic": "Cách học tiếng Anh hiệu quả", "keyword": "học tiếng Anh"},
            {"topic": "Top 10 địa điểm du lịch Hà Nội", "keyword": "du lịch Hà Nội"},
        ],
    )
    result = parse_excel(xlsx)
    assert len(result) == 2
    assert result[0]["topic"] == "Cách học tiếng Anh hiệu quả"
    assert result[0]["keyword"] == "học tiếng Anh"


def test_parse_excel_no_keyword(tmp_dir):
    xlsx = make_xlsx(
        tmp_dir / "topics.xlsx",
        [{"topic": "Sức khỏe tâm thần"}],
    )
    result = parse_excel(xlsx)
    assert result[0]["keyword"] is None


def test_parse_excel_empty(tmp_dir):
    wb = openpyxl.Workbook()
    wb.active.title = "Sheet1"
    path = tmp_dir / "empty.xlsx"
    wb.save(path)
    result = parse_excel(path)
    assert result == []


def test_parse_json_list(tmp_dir):
    data = [
        {"topic": "Ẩm thực Việt Nam", "keyword": "ẩm thực"},
        {"topic": "Phở Hà Nội"},
    ]
    path = tmp_dir / "topics.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = parse_json(path)
    assert len(result) == 2
    assert result[1]["keyword"] is None


def test_parse_json_envelope(tmp_dir):
    data = {"topics": [{"topic": "Văn hóa Việt", "keyword": "văn hóa"}]}
    path = tmp_dir / "topics.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = parse_json(path)
    assert len(result) == 1


def test_parse_json_plain_strings(tmp_dir):
    data = ["Chủ đề 1", "Chủ đề 2"]
    path = tmp_dir / "topics.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = parse_json(path)
    assert len(result) == 2
    assert result[0]["topic"] == "Chủ đề 1"


def test_parse_input_dispatches_excel(tmp_dir):
    xlsx = make_xlsx(tmp_dir / "t.xlsx", [{"topic": "Test"}])
    result = parse_input(xlsx)
    assert len(result) == 1


def test_parse_input_dispatches_json(tmp_dir):
    path = tmp_dir / "t.json"
    path.write_text(json.dumps([{"topic": "Test JSON"}]), encoding="utf-8")
    result = parse_input(path)
    assert len(result) == 1


def test_parse_input_unsupported_format(tmp_dir):
    path = tmp_dir / "topics.csv"
    path.write_text("topic\nTest", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file format"):
        parse_input(path)

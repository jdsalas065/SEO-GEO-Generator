"""Unit tests for image search and figure injection."""
from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from app.image_search import (
    attach_images,
    extract_h2_headings,
    fetch_bing_image_url,
    head_content_type_check,
    inject_figures,
    is_valid_image_url,
    score_h2,
    select_h2s_for_images,
)


def test_extract_h2_headings() -> None:
    """Only Markdown H2 headings with exact '## ' prefix should be extracted."""
    md = """# Title

## First H2
### Not H2
## Second H2
##
## Third H2
"""

    result = extract_h2_headings(md)
    assert result == [(2, "First H2"), (4, "Second H2"), (6, "Third H2")]


def test_keyword_match_scoring_and_select_top3_tiebreaker() -> None:
    """Select top 3 headings by score, using earliest heading for score ties."""
    h2s = [
        (2, "Huong dan SEO co ban"),
        (8, "SEO onpage cho nguoi moi"),
        (11, "No match heading"),
        (15, "Toi uu SEO va content"),
        (20, "SEO technical checklist"),
    ]
    keyword_tokens = ["seo", "content"]

    assert score_h2("Toi uu SEO va content", keyword_tokens) == 2
    assert score_h2("No match heading", keyword_tokens) == 0

    selected = select_h2s_for_images(h2s, keyword_tokens, max_n=3)
    assert selected == [
        (15, "Toi uu SEO va content"),
        (2, "Huong dan SEO co ban"),
        (8, "SEO onpage cho nguoi moi"),
    ]


def test_inject_figures_inserts_immediately_after_h2() -> None:
    """Figure HTML should be placed directly under selected H2 line."""
    md = """# Tieu de

## Muc 1
Noi dung 1

## Muc 2
Noi dung 2
"""
    figure = "<figure>\n  <img src=\"https://x/y.jpg\" alt=\"Muc 1\" loading=\"lazy\">\n  <figcaption>Muc 1</figcaption>\n</figure>"

    output = inject_figures(md, {2: figure})
    lines = output.splitlines()

    assert lines[2] == "## Muc 1"
    assert lines[3] == "<figure>"
    assert lines[7] == "Noi dung 1"


def test_gif_url_filtering(monkeypatch) -> None:
    """GIF URLs should be rejected from URL string checks before HEAD request."""
    monkeypatch.setattr("app.image_search.head_content_type_check", lambda _url: True)

    assert is_valid_image_url("https://example.com/a.gif") is False
    assert is_valid_image_url("https://example.com/a.GIF?x=1") is False
    assert is_valid_image_url("https://example.com/a.jpg") is True


def test_head_content_type_filtering(monkeypatch) -> None:
    """HEAD content-type checks should reject GIF and request failures."""
    ok_resp = MagicMock()
    ok_resp.headers = {"Content-Type": "image/jpeg"}

    gif_resp = MagicMock()
    gif_resp.headers = {"Content-Type": "image/gif"}

    monkeypatch.setattr("app.image_search.httpx.head", lambda *args, **kwargs: ok_resp)
    assert head_content_type_check("https://example.com/a.jpg") is True

    monkeypatch.setattr("app.image_search.httpx.head", lambda *args, **kwargs: gif_resp)
    assert head_content_type_check("https://example.com/a.gif") is False

    def _raise_http_error(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.HTTPError("boom")

    monkeypatch.setattr("app.image_search.httpx.head", _raise_http_error)
    assert head_content_type_check("https://example.com/a.jpg") is False


def test_fallback_selection_prefers_rank3_then_next_candidates(monkeypatch) -> None:
    """When rank-3 candidate is invalid, fallback should continue with later candidates."""
    candidates = [
        "https://img.example.com/1.jpg",
        "https://img.example.com/2.jpg",
        "https://img.example.com/3.jpg",
        "https://img.example.com/4.jpg",
    ]

    monkeypatch.setattr("app.image_search._fetch_bing_candidates", lambda *args, **kwargs: candidates)

    def _is_valid(url: str) -> bool:
        return url.endswith("4.jpg")

    monkeypatch.setattr("app.image_search.is_valid_image_url", _is_valid)

    url = fetch_bing_image_url(
        query="seo viet nam",
        desired_rank=3,
        timeout=20,
        max_candidates=10,
    )

    assert url == "https://img.example.com/4.jpg"


def test_attach_images_fallbacks_to_first_h2_when_no_keyword_matches(monkeypatch) -> None:
    """When score-based selection yields none, fallback should still attach images to early H2s."""
    md = """# Tieu de

## Chu de A
Noi dung A

## Chu de B
Noi dung B
"""

    monkeypatch.setattr("app.image_search.IMAGE_SEARCH_ENGINE", "bing")
    monkeypatch.setattr("app.image_search.IMAGE_MAX_PER_ARTICLE", 2)
    monkeypatch.setattr(
        "app.image_search.fetch_bing_image_url",
        lambda **kwargs: "https://img.example.com/a.jpg",
    )

    new_md, images = attach_images(md, topic="va va va", keyword=None, article_id="a1")

    assert len(images) == 2
    assert images[0]["h2"] == "Chu de A"
    assert images[1]["h2"] == "Chu de B"
    assert "<figure>" in new_md

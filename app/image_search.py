"""Image search and Markdown figure injection utilities."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from html import escape
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

logger = logging.getLogger(__name__)

IMAGE_SEARCH_ENGINE = os.environ.get("IMAGE_SEARCH_ENGINE", "bing").strip().lower()
IMAGE_MAX_PER_ARTICLE = int(os.environ.get("IMAGE_MAX_PER_ARTICLE", "3"))
IMAGE_RESULT_RANK = int(os.environ.get("IMAGE_RESULT_RANK", "3"))
IMAGE_SEARCH_TIMEOUT_SECONDS = int(os.environ.get("IMAGE_SEARCH_TIMEOUT_SECONDS", "20"))
IMAGE_SEARCH_MAX_CANDIDATES = int(os.environ.get("IMAGE_SEARCH_MAX_CANDIDATES", "10"))

_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)
_WORD_TEMPLATE = r"(?<!\w){}(?!\w)"

_STOPWORDS = {
    "a",
    "an",
    "and",
    "cho",
    "cua",
    "các",
    "cach",
    "cần",
    "cũng",
    "de",
    "để",
    "đến",
    "do",
    "gì",
    "hay",
    "khi",
    "không",
    "la",
    "là",
    "một",
    "nhung",
    "những",
    "or",
    "sẽ",
    "the",
    "thì",
    "this",
    "to",
    "trong",
    "va",
    "và",
    "về",
    "với",
}


def extract_h2_headings(md: str) -> list[tuple[int, str]]:
    """Return H2 headings as tuples of (line_index, heading_text)."""
    headings: list[tuple[int, str]] = []
    for idx, line in enumerate(md.splitlines()):
        if line.startswith("## "):
            heading = line[3:].strip()
            if heading:
                headings.append((idx, heading))
    return headings


def tokenize_keywords(text: str) -> list[str]:
    """Tokenize a text into lowercase keyword tokens without stopwords."""
    tokens: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_RE.findall(text.lower()):
        if len(token) <= 1 or token in _STOPWORDS:
            continue
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def score_h2(heading: str, keyword_tokens: list[str]) -> int:
    """Score heading by counting keyword-token whole-word matches (case-insensitive)."""
    score = 0
    for token in keyword_tokens:
        pattern = _WORD_TEMPLATE.format(re.escape(token))
        if re.search(pattern, heading, flags=re.IGNORECASE):
            score += 1
    return score


def select_h2s_for_images(
    h2s: list[tuple[int, str]],
    keyword_tokens: list[str],
    max_n: int,
) -> list[tuple[int, str]]:
    """Select top-scoring H2 headings and break ties by original document order."""
    scored: list[tuple[int, int, str]] = []
    for idx, heading in h2s:
        score = score_h2(heading, keyword_tokens)
        if score > 0:
            scored.append((score, idx, heading))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(idx, heading) for _, idx, heading in scored[:max_n]]


def build_figure_html(image_url: str, alt: str, caption: str) -> str:
    """Build an HTML figure block for Markdown insertion."""
    return (
        "<figure>\n"
        f"  <img src=\"{escape(image_url, quote=True)}\" alt=\"{escape(alt, quote=True)}\" loading=\"lazy\">\n"
        f"  <figcaption>{escape(caption)}</figcaption>\n"
        "</figure>"
    )


def inject_figures(md: str, selected_h2_to_figure_html: dict[int, str]) -> str:
    """Inject figure HTML immediately after selected H2 line indices."""
    if not selected_h2_to_figure_html:
        return md

    lines = md.splitlines()
    output: list[str] = []
    for idx, line in enumerate(lines):
        output.append(line)
        figure = selected_h2_to_figure_html.get(idx)
        if figure:
            output.append(figure)

    return "\n".join(output) + ("\n" if md.endswith("\n") else "")


def _bing_images_url(query: str) -> str:
    encoded_query = quote_plus(query)
    return (
        "https://www.bing.com/images/search"
        f"?q={encoded_query}&qft=+filterui:photo-photo&form=IRFLTR"
    )


def _fetch_bing_candidates(query: str, timeout: int, max_candidates: int) -> list[str]:
    """Fetch Bing image candidate URLs from image result metadata."""
    from playwright.sync_api import sync_playwright

    url = _bing_images_url(query)
    candidates: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")

            locator = page.locator("a.iusc")
            count = locator.count()
            for idx in range(count):
                if len(candidates) >= max_candidates:
                    break
                metadata = locator.nth(idx).get_attribute("m")
                if not metadata:
                    continue
                try:
                    payload = json.loads(metadata)
                except json.JSONDecodeError:
                    continue
                image_url = payload.get("murl")
                if isinstance(image_url, str) and image_url:
                    candidates.append(image_url)

            return candidates
        finally:
            browser.close()


def head_content_type_check(url: str, timeout_seconds: float = 5.0) -> bool:
    """Return False when content-type indicates GIF or when HEAD request fails."""
    try:
        response = httpx.head(url, follow_redirects=True, timeout=timeout_seconds)
    except httpx.HTTPError:
        return False

    content_type = response.headers.get("Content-Type", "").lower()
    if not content_type:
        return False
    return not content_type.startswith("image/gif")


def is_valid_image_url(url: str) -> bool:
    """Validate image URL and reject GIFs via URL and HEAD checks."""
    if not url:
        return False

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False

    lowered = url.lower()
    if lowered.endswith(".gif") or ".gif?" in lowered:
        return False

    return head_content_type_check(url)


def fetch_bing_image_url(
    query: str,
    desired_rank: int,
    timeout: int,
    max_candidates: int,
) -> str | None:
    """Fetch one valid image URL from Bing, preferring desired rank then fallbacks."""
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    except Exception:
        logger.exception("Playwright is unavailable for query='%s'", query)
        return None

    start = time.monotonic()
    try:
        candidates = _fetch_bing_candidates(query, timeout, max_candidates)
    except PlaywrightTimeoutError:
        logger.warning("Bing image search timeout for query='%s'", query)
        return None
    except Exception:
        logger.exception("Bing image search failed for query='%s'", query)
        return None

    if not candidates:
        return None

    desired_idx = max(desired_rank - 1, 0)
    if desired_idx < len(candidates):
        indices = [desired_idx]
        indices.extend(idx for idx in range(desired_idx + 1, len(candidates)))
        indices.extend(idx for idx in range(0, desired_idx))
    else:
        indices = list(range(len(candidates)))

    for idx in indices:
        if time.monotonic() - start > timeout:
            return None
        url = candidates[idx]
        if is_valid_image_url(url):
            return url
    return None


def attach_images(
    md_content: str,
    topic: str,
    keyword: str | None,
    article_id: str | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Attach up to IMAGE_MAX_PER_ARTICLE figures after selected H2 headings."""
    if IMAGE_SEARCH_ENGINE != "bing":
        logger.warning("Unsupported IMAGE_SEARCH_ENGINE='%s', skipping images", IMAGE_SEARCH_ENGINE)
        return md_content, []

    h2s = extract_h2_headings(md_content)
    if not h2s:
        return md_content, []

    base = keyword.strip() if keyword and keyword.strip() else topic.strip()
    keyword_tokens = tokenize_keywords(base)
    if not keyword_tokens:
        return md_content, []

    selected = select_h2s_for_images(h2s, keyword_tokens, IMAGE_MAX_PER_ARTICLE)
    if not selected:
        return md_content, []

    figures_by_h2_index: dict[int, str] = {}
    images_json: list[dict[str, Any]] = []

    for idx, heading in selected:
        query = f"{base} {heading}".strip()
        try:
            image_url = fetch_bing_image_url(
                query=query,
                desired_rank=IMAGE_RESULT_RANK,
                timeout=IMAGE_SEARCH_TIMEOUT_SECONDS,
                max_candidates=IMAGE_SEARCH_MAX_CANDIDATES,
            )
        except Exception:
            logger.exception(
                "Image search error article_id=%s h2='%s' query='%s'",
                article_id,
                heading,
                query,
            )
            continue

        if not image_url:
            logger.warning(
                "Image search returned no valid image article_id=%s h2='%s' query='%s'",
                article_id,
                heading,
                query,
            )
            continue

        alt_text = heading
        caption = heading
        figures_by_h2_index[idx] = build_figure_html(image_url, alt_text, caption)
        images_json.append(
            {
                "h2": heading,
                "query": query,
                "image_url": image_url,
                "alt": alt_text,
                "caption": caption,
                "rank": IMAGE_RESULT_RANK,
                "engine": "bing",
            }
        )

    return inject_figures(md_content, figures_by_h2_index), images_json
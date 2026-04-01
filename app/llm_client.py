"""Pluggable LLM client supporting Anthropic, OpenAI, and Google Gemini."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_RULES_PATH = Path(__file__).parent.parent / "config" / "rules.yaml"


def _load_llm_config() -> dict[str, Any]:
    with _RULES_PATH.open(encoding="utf-8") as fh:
        rules = yaml.safe_load(fh)
    return rules.get("llm", {})


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


def _call_anthropic(prompt: str, cfg: dict[str, Any]) -> str:
    import anthropic  # type: ignore[import-untyped]

    api_key = os.environ.get(cfg.get("api_key_env", "ANTHROPIC_API_KEY"), "")
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=cfg.get("model", "claude-3-5-sonnet-20241022"),
        max_tokens=cfg.get("max_tokens", 4096),
        temperature=cfg.get("temperature", 0.7),
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_openai(prompt: str, cfg: dict[str, Any]) -> str:
    from openai import OpenAI  # type: ignore[import-untyped]

    api_key = os.environ.get(cfg.get("api_key_env", "OPENAI_API_KEY"), "")
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=cfg.get("model", "gpt-4o"),
        max_tokens=cfg.get("max_tokens", 4096),
        temperature=cfg.get("temperature", 0.7),
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def _call_gemini(prompt: str, cfg: dict[str, Any]) -> str:
    import google.generativeai as genai  # type: ignore[import-untyped]

    api_key = os.environ.get(cfg.get("api_key_env", "GEMINI_API_KEY"), "")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(cfg.get("model", "gemini-1.5-pro"))
    response = model.generate_content(prompt)
    return response.text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_PROVIDERS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
}


def call_llm(prompt: str, config_override: dict[str, Any] | None = None) -> str:
    """Call the configured LLM and return the raw text response."""
    cfg = _load_llm_config()
    if config_override:
        cfg.update(config_override)

    provider = cfg.get("provider", "anthropic").lower()
    handler = _PROVIDERS.get(provider)
    if handler is None:
        raise ValueError(f"Unknown LLM provider: {provider!r}")

    return handler(prompt, cfg)

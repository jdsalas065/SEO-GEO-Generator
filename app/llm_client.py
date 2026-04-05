"""Pluggable LLM client supporting Anthropic, OpenAI, and Google Gemini."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

_RULES_PATH = Path(__file__).parent.parent / "config" / "rules.yaml"


def _get_required_secret(var_name: str, provider: str) -> str:
    """Return a required secret env var or raise a clear configuration error."""
    value = (os.environ.get(var_name) or "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable {var_name!r} for provider {provider!r}."
        )
    return value


def _load_llm_config() -> dict[str, Any]:
    with _RULES_PATH.open(encoding="utf-8") as fh:
        rules = yaml.safe_load(fh)
    return rules.get("llm", {})


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


def _call_anthropic(prompt: str, cfg: dict[str, Any]) -> str:
    import anthropic  # type: ignore[import-untyped]

    api_key = _get_required_secret(cfg.get("api_key_env", "ANTHROPIC_API_KEY"), "anthropic")
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

    api_key = _get_required_secret(cfg.get("api_key_env", "OPENAI_API_KEY"), "openai")
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

    api_key = _get_required_secret(cfg.get("api_key_env", "GEMINI_API_KEY"), "gemini")
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


class LLMJsonParseError(Exception):
    """Raised when LLM response cannot be parsed as JSON."""
    pass


class LLMClient:
    """LLM client configured from a step config."""

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize from a step config dictionary."""
        self.config = config
        self.provider = config.get("provider", "anthropic").lower()
        self.model = config.get("model", "claude-3-5-sonnet-20241022")
        self.temperature = config.get("temperature", 0.7)
        self.max_tokens = config.get("max_tokens", 4096)

    @classmethod
    def from_step_config(cls, step_cfg: dict[str, Any]) -> LLMClient:
        """Create LLMClient from a step configuration (outline/write/seo_check)."""
        return cls(step_cfg)

    def generate(self, prompt: str | dict[str, Any]) -> str:
        """Generate text response from LLM."""
        if isinstance(prompt, dict):
            # If prompt is a dict with system/user keys, join them
            system_msg = prompt.get("system", "")
            user_msg = prompt.get("user", "")
            full_prompt = f"{system_msg}\n\n{user_msg}".strip()
        else:
            full_prompt = prompt

        handler = _PROVIDERS.get(self.provider)
        if handler is None:
            raise ValueError(f"Unknown LLM provider: {self.provider!r}")

        return handler(full_prompt, self.config)

    def generate_json(self, prompt: str | dict[str, Any], max_retries: int = 1) -> dict[str, Any]:
        """
        Generate JSON response from LLM.
        If initial parse fails, retry once with JSON hint.
        
        Args:
            prompt: The prompt (str or dict with system/user keys)
            max_retries: Number of retries on parse failure
            
        Returns:
            Parsed JSON as dictionary
            
        Raises:
            LLMJsonParseError: If JSON parsing fails after retries
        """
        prompt_to_send: str | dict[str, Any] = prompt
        for attempt in range(max_retries + 1):
            response = self.generate(prompt_to_send)
            
            # Try to extract JSON from response (handle markdown code fences)
            json_str = response.strip()
            
            # Remove markdown code fences if present
            json_str = re.sub(r"^```(?:json)?\n?", "", json_str)
            json_str = re.sub(r"\n?```$", "", json_str)
            json_str = json_str.strip()
            
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                if attempt < max_retries:
                    # Retry with JSON hint
                    if isinstance(prompt_to_send, dict):
                        prompt_for_retry = dict(prompt_to_send)
                        prompt_for_retry["user"] = prompt_for_retry.get("user", "") + "\n\nPlease respond with ONLY valid JSON, no markdown formatting."
                    else:
                        prompt_for_retry = prompt_to_send + "\n\nPlease respond with ONLY valid JSON, no markdown formatting."
                    prompt_to_send = prompt_for_retry
                    continue
                else:
                    raise LLMJsonParseError(
                        f"Failed to parse JSON response after {max_retries + 1} attempts. "
                        f"Last error: {e}\nResponse: {response[:200]}"
                    )


def call_llm(prompt: str, config_override: dict[str, Any] | None = None) -> str:
    """Call the configured LLM and return the raw text response (legacy API)."""
    cfg = _load_llm_config()
    # Remove 'steps' key if present (it's for multi-step pipeline)
    cfg.pop("steps", None)
    
    if config_override:
        cfg.update(config_override)

    provider = cfg.get("provider", "anthropic").lower()
    handler = _PROVIDERS.get(provider)
    if handler is None:
        raise ValueError(f"Unknown LLM provider: {provider!r}")

    return handler(prompt, cfg)

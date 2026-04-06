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


def _extract_json_candidate(response: str) -> str:
    """Extract the most likely JSON object from an LLM response."""
    text = response.strip()

    # Prefer fenced JSON blocks when present.
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()

    # Remove a single pair of surrounding code fences if any.
    text = re.sub(r"^```(?:json)?\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()

    # Extract the first balanced JSON object while respecting quoted strings.
    start = text.find("{")
    if start == -1:
        return text

    depth = 0
    in_string = False
    escaped = False
    for idx, ch in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1].strip()

    # Fallback: keep the original string for error reporting/retry.
    return text


def _build_json_repair_prompt(raw_response: str) -> str:
    """Build a strict repair prompt to recover valid JSON from malformed output."""
    return (
        "You are a JSON repair tool.\n"
        "Convert the malformed content below into ONE valid JSON object.\n"
        "Rules:\n"
        "- Return ONLY JSON object\n"
        "- No markdown fences\n"
        "- No explanations\n"
        "- Keep keys and structure as close as possible\n"
        "- If content is truncated, complete minimally to valid JSON\n\n"
        "Malformed content:\n"
        f"{raw_response[:6000]}"
    )


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
        last_response = ""
        last_error: json.JSONDecodeError | None = None
        for attempt in range(max_retries + 1):
            response = self.generate(prompt_to_send)
            last_response = response
            json_str = _extract_json_candidate(response)
            
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                last_error = e
                if attempt < max_retries:
                    # Retry with JSON hint
                    if isinstance(prompt_to_send, dict):
                        prompt_for_retry = dict(prompt_to_send)
                        prompt_for_retry["user"] = (
                            prompt_for_retry.get("user", "")
                            + "\n\nCRITICAL: Respond with ONLY one valid JSON object."
                            + " No markdown, no explanation, no trailing text."
                        )
                    else:
                        prompt_for_retry = (
                            prompt_to_send
                            + "\n\nCRITICAL: Respond with ONLY one valid JSON object."
                            + " No markdown, no explanation, no trailing text."
                        )
                    prompt_to_send = prompt_for_retry
                    continue

        # Final fallback: ask the same model to repair malformed JSON.
        repair_prompt = _build_json_repair_prompt(last_response)
        repaired_response = self.generate(repair_prompt)
        repaired_json = _extract_json_candidate(repaired_response)
        try:
            return json.loads(repaired_json)
        except json.JSONDecodeError:
            err_text = str(last_error) if last_error is not None else "unknown JSON parse error"
            raise LLMJsonParseError(
                f"Failed to parse JSON response after {max_retries + 1} attempts and repair fallback. "
                f"Last error: {err_text}\nResponse: {last_response[:200]}"
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

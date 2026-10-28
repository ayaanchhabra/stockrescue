"""Minimal, provider-agnostic LLM client for the explanation step.

Returns a plain `complete(prompt) -> str` callable, which is all
app.agent.explanation needs. No vendor SDKs: requests go through httpx.

Providers
  openai_compatible  POST {base_url}/chat/completions (OpenAI, Groq, OpenRouter,
                     Together, Gemini's OpenAI-compatible endpoint, local Ollama)
  anthropic          POST {base_url}/v1/messages

Configuration comes from environment variables (or backend/.env):
  LLM_PROVIDER        empty/unset = LLM explanations disabled
  LLM_API_KEY, LLM_MODEL, LLM_BASE_URL (optional),
  LLM_TIMEOUT_SECONDS (default 20), LLM_MAX_TOKENS (default 800)

The key is never logged and never included in an error message. Nothing here
runs at import time.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

OPENAI_COMPATIBLE = "openai_compatible"
ANTHROPIC = "anthropic"
PROVIDERS = (OPENAI_COMPATIBLE, ANTHROPIC)

_DEFAULT_BASE = {
    OPENAI_COMPATIBLE: "https://api.openai.com/v1",
    ANTHROPIC: "https://api.anthropic.com",
}
ANTHROPIC_VERSION = "2023-06-01"

CompleteFn = Callable[[str], str]


class LLMError(Exception):
    """The provider could not produce a reply (status, timeout or bad body)."""


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="LLM_", extra="ignore")

    provider: str = ""
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    timeout_seconds: float = 20.0
    max_tokens: int = 800


def _openai_request(base: str, key: str, model: str, prompt: str, max_tokens: int):
    url = base.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    return url, headers, body


def _openai_text(data: object) -> str:
    return data["choices"][0]["message"]["content"]  # type: ignore[index]


def _anthropic_request(base: str, key: str, model: str, prompt: str, max_tokens: int):
    url = base.rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    return url, headers, body


def _anthropic_text(data: object) -> str:
    blocks = data["content"]  # type: ignore[index]
    texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type", "text") == "text"]
    if not texts:
        raise KeyError("no text blocks")
    return "".join(texts)


def make_completer(
    provider: str,
    api_key: str,
    model: str,
    *,
    base_url: Optional[str] = None,
    timeout: float = 20.0,
    max_tokens: int = 800,
    transport: Optional[httpx.BaseTransport] = None,
) -> CompleteFn:
    """Build a `complete(prompt) -> str` for one provider."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown LLM provider '{provider}'; expected one of {PROVIDERS}")
    if not api_key or not model:
        raise ValueError("an LLM provider needs both an api key and a model")
    base = base_url or _DEFAULT_BASE[provider]
    build = _openai_request if provider == OPENAI_COMPATIBLE else _anthropic_request
    parse = _openai_text if provider == OPENAI_COMPATIBLE else _anthropic_text

    def complete(prompt: str) -> str:
        url, headers, body = build(base, api_key, model, prompt, max_tokens)
        try:
            with httpx.Client(transport=transport, timeout=timeout) as client:
                r = client.post(url, headers=headers, json=body)
        except httpx.TimeoutException:
            raise LLMError("LLM request timed out") from None
        except httpx.HTTPError as e:
            raise LLMError(f"Network error talking to the LLM ({type(e).__name__})") from None
        if r.status_code != 200:
            raise LLMError(f"LLM provider returned HTTP {r.status_code}")
        try:
            text = parse(r.json())
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("LLM provider returned an unexpected response body") from None
        if not isinstance(text, str):
            raise LLMError("LLM provider returned a non-text reply")
        return text

    return complete


def completer_from_env(settings: Optional[LLMSettings] = None) -> Optional[CompleteFn]:
    """The configured completer, or None when LLM explanations are disabled or
    misconfigured (a warning is logged; the app keeps working without them)."""
    s = settings if settings is not None else LLMSettings()
    provider = s.provider.strip().lower()
    if not provider:
        return None
    try:
        return make_completer(
            provider, s.api_key.strip(), s.model.strip(),
            base_url=s.base_url.strip() or None,
            timeout=s.timeout_seconds, max_tokens=s.max_tokens,
        )
    except ValueError as e:
        log.warning("LLM explanations disabled: %s", e)
        return None
